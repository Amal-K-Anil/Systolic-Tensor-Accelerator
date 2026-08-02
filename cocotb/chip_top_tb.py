# SPDX-FileCopyrightText: © 2025 Project Template Contributors
# SPDX-License-Identifier: Apache-2.0

import os
import logging
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, RisingEdge, FallingEdge, ClockCycles
from cocotb.types import LogicArray
from cocotb_tools.runner import get_runner

sim = os.getenv("SIM", "icarus")
pdk_root = os.getenv("PDK_ROOT", Path("~/.ciel").expanduser())
pdk = os.getenv("PDK", "gf180mcuD")
scl = os.getenv("SCL", "gf180mcu_fd_sc_mcu7t5v0")
gl = os.getenv("GL", "0").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
slot = os.getenv("SLOT", "1x1")

hdl_toplevel = "chip_top"

# Shared data bus
DATA_LSB = 0
DATA_WIDTH = 8

# Host-to-accelerator control pads
PAD_VALID_IN = 8
PAD_TILE_DONE = 9
PAD_LAST_PASS = 10
PAD_READY_OUT = 11

# Accelerator-to-host status pads
PAD_READY_IN = 12
PAD_VALID_OUT = 13

TILE_BYTES = 128
OUTPUT_BYTES = 64

def make_host_bidir_value(
    width: int,
    *,
    data: int = 0,
    drive_data: bool = True,
    valid_in: int = 0,
    tile_done: int = 0,
    last_pass: int = 0,
    ready_out: int = 0,
) -> LogicArray:
    """
    Construct the external value driven onto bidir_PAD.

    The list is indexed by physical bit number. It is reversed before creating
    LogicArray because the HDL vector is declared [WIDTH-1:0].
    """
    bits = ["Z"] * width

    if drive_data:
        for bit_index in range(DATA_WIDTH):
            bits[bit_index] = (
                "1" if ((data >> bit_index) & 1) else "0"
            )

    control_values = {
        PAD_VALID_IN: valid_in,
        PAD_TILE_DONE: tile_done,
        PAD_LAST_PASS: last_pass,
        PAD_READY_OUT: ready_out,
    }

    for bit_index, bit_value in control_values.items():
        bits[bit_index] = "1" if bit_value else "0"

    return LogicArray("".join(reversed(bits)))


def drive_host_pads(
    dut,
    *,
    data: int = 0,
    drive_data: bool = True,
    valid_in: int = 0,
    tile_done: int = 0,
    last_pass: int = 0,
    ready_out: int = 0,
) -> None:
    dut.bidir_PAD.value = make_host_bidir_value(
        len(dut.bidir_PAD),
        data=data,
        drive_data=drive_data,
        valid_in=valid_in,
        tile_done=tile_done,
        last_pass=last_pass,
        ready_out=ready_out,
    )


def read_bidir_bit(dut, bit_index: int) -> int:
    return int(dut.bidir_PAD.value[bit_index])


def read_output_data(dut) -> int:
    value = 0

    for bit_index in range(DATA_WIDTH):
        value |= (
            int(dut.bidir_PAD.value[bit_index])
            << bit_index
        )

    return value

async def set_defaults(dut):
    # Discrete input pads are unused.
    dut.input_PAD.value = 0

    # Drive accelerator controls low and drive zero on the input data bus.
    drive_host_pads(
        dut,
        data=0,
        drive_data=True,
        valid_in=0,
        tile_done=0,
        last_pass=0,
        ready_out=0,
    )

    # Leave analog pads undriven.
    dut.analog_PAD.value = LogicArray(
        "Z" * len(dut.analog_PAD)
    )


async def enable_power(dut):
    dut.VDD.value = 1
    dut.VSS.value = 0


async def start_clock(clock, freq=25):
    """Start the accelerator clock at 25 MHz: 40 ns period."""
    period_ns = 1000 / freq

    cocotb.start_soon(
        Clock(clock, period_ns, unit="ns").start()
    )


async def reset(reset_signal, active_low=True, time_ns=1000):
    cocotb.log.info("Reset asserted")

    reset_signal.value = 0 if active_low else 1
    await Timer(time_ns, unit="ns")

    reset_signal.value = 1 if active_low else 0
    await Timer(1, unit="ns")

    cocotb.log.info("Reset deasserted")


async def start_up(dut):
    if gl:
        await enable_power(dut)
        await Timer(10, unit="ns")

    await set_defaults(dut)
    await start_clock(dut.clk_PAD, freq=25)
    await reset(dut.rst_n_PAD)


@cocotb.test()
async def test_accelerator_chip_smoke(dut):
    """
    Chip-level accelerator smoke test.

    The test:
      1. resets chip_top,
      2. checks ready_in,
      3. sends one 128-byte final tile,
      4. waits for 64 output transfers,
      5. checks that the accelerator returns to ready state.

    An all-zero tile is used so this chip-wrapper test remains independent of
    the known GF180 SRAM behavioral-model address-rotation issue.
    """

    logger = logging.getLogger("accelerator_chip_tb")

    assert len(dut.bidir_PAD) >= 14, (
        "The accelerator wrapper requires at least "
        "14 bidirectional pads"
    )

    logger.info("Starting chip-level accelerator test")

    await start_up(dut)
    await ClockCycles(dut.clk_PAD, 2)
    await Timer(1, unit="ns")

    ready_in = read_bidir_bit(
        dut,
        PAD_READY_IN,
    )

    assert ready_in == 1, (
        "ready_in was not asserted after reset"
    )

    logger.info("ready_in asserted after reset")

    # -------------------------------------------------------------------------
    # Send one final 128-byte tile
    # -------------------------------------------------------------------------
    #
    # A = all zero
    # B = all zero
    #
    # Expected output: 64 zero-valued results.

    for byte_index in range(TILE_BYTES):
        final_byte = byte_index == TILE_BYTES - 1

        await FallingEdge(dut.clk_PAD)

        drive_host_pads(
            dut,
            data=0x00,
            drive_data=True,
            valid_in=1,
            tile_done=int(final_byte),
            last_pass=int(final_byte),
            ready_out=0,
        )

        await RisingEdge(dut.clk_PAD)
        await Timer(1, unit="ns")

    # -------------------------------------------------------------------------
    # End input transfer and release the shared data bus
    # -------------------------------------------------------------------------

    await FallingEdge(dut.clk_PAD)

    drive_host_pads(
        dut,
        drive_data=False,
        valid_in=0,
        tile_done=0,
        last_pass=0,
        ready_out=1,
    )

    logger.info(
        "Final tile loaded; waiting for accelerator output"
    )

    # -------------------------------------------------------------------------
    # Receive result bytes
    # -------------------------------------------------------------------------

    output_values = []

    for cycle in range(2000):
        # Sample valid_out and data during the stable half-cycle before
        # the rising edge on which ready_out accepts the result.
        await FallingEdge(dut.clk_PAD)
        await Timer(1, unit="ns")

        valid_out = read_bidir_bit(
            dut,
            PAD_VALID_OUT,
        )

        accepted_value = None

        if valid_out:
            accepted_value = read_output_data(dut)

        await RisingEdge(dut.clk_PAD)
        await Timer(1, unit="ns")

        if accepted_value is not None:
            output_values.append(accepted_value)

            logger.info(
                "Output %02d/%02d = 0x%02X",
                len(output_values),
                OUTPUT_BYTES,
                accepted_value,
            )

            if len(output_values) == OUTPUT_BYTES:
                break

    assert len(output_values) == OUTPUT_BYTES, (
        f"Expected {OUTPUT_BYTES} output transfers, "
        f"received {len(output_values)}"
    )

    assert all(value == 0 for value in output_values), (
        "All-zero matrices must produce all-zero outputs: "
        f"{output_values}"
    )

    # -------------------------------------------------------------------------
    # Check that the accelerator returns to the input-ready state
    # -------------------------------------------------------------------------

    ready_returned = False

    for _ in range(10):
        await RisingEdge(dut.clk_PAD)
        await Timer(1, unit="ns")

        if read_bidir_bit(dut, PAD_READY_IN):
            ready_returned = True
            break

    assert ready_returned, (
        "Accelerator did not return to ready state after output"
    )

    logger.info(
        "PASS: chip_top accepted one 128-byte tile, "
        "produced 64 zero outputs, and returned to ready"
    )


def chip_top_runner():
    proj_path = Path(__file__).resolve().parent

    wrapper_dir = (
        proj_path / "../src/chipathon_wrapper"
    )

    core_dir = (
        proj_path / "../src/core"
    )

    sources = []

    slot_define = f"SLOT_{slot.upper()}"

    defines = {
        slot_define: True,
        "FUNCTIONAL": True,
    }

    includes = [
        proj_path / "../src",
        wrapper_dir,
        core_dir,
    ]

    if gl:
        # Standard-cell simulation models
        sources += [
            Path(pdk_root)
            / pdk
            / "libs.ref"
            / scl
            / "verilog"
            / f"{scl}.v",

            Path(pdk_root)
            / pdk
            / "libs.ref"
            / scl
            / "verilog"
            / "primitives.v",

            # Powered post-layout netlist
            proj_path
            / f"../final/pnl/{hdl_toplevel}.pnl.v",
        ]

        defines["USE_POWER_PINS"] = True

    else:
        sources += [
            # Accelerator implementation
            core_dir / "booth_encoder.sv",
            core_dir / "ppdt_booth.sv",
            core_dir / "booth_multiplier.sv",
            core_dir / "mac_unit.sv",
            core_dir / "systolic_array.sv",
            core_dir / "output_processor.sv",
            core_dir / "memory.sv",
            core_dir / "feeder.sv",
            core_dir / "controller.sv",
            core_dir / "accelerator_core.sv",

            # Chipathon wrapper
            wrapper_dir / "chip_core.sv",
            wrapper_dir / "chip_top.sv",
        ]

    sources += [
        # IO pad models
        Path(pdk_root)
        / pdk
        / "libs.ref/gf180mcu_fd_io/verilog/"
          "gf180mcu_fd_io.v",

        Path(pdk_root)
        / pdk
        / "libs.ref/gf180mcu_fd_io/verilog/"
          "gf180mcu_ws_io.v",

        # Correct SRAM macro for accelerator_core
        Path(pdk_root)
        / pdk
        / "libs.ref/gf180mcu_fd_ip_sram/verilog/"
          "gf180mcu_fd_ip_sram__sram128x8m8wm1.v",

        # Required custom IP
        proj_path
        / "../ip/gf180mcu_ws_ip__id/vh/"
          "gf180mcu_ws_ip__id.v",

        proj_path
        / "../ip/gf180mcu_ws_ip__logo/vh/"
          "gf180mcu_ws_ip__logo.v",
    ]

    build_args = []

    if sim == "verilator":
        build_args = [
            "--timing",
            "--trace",
            "--trace-fst",
            "--trace-structs",
        ]

    runner = get_runner(sim)

    runner.build(
        sources=sources,
        hdl_toplevel=hdl_toplevel,
        defines=defines,
        always=True,
        includes=includes,
        build_args=build_args,
        waves=True,
    )

    runner.test(
        hdl_toplevel=hdl_toplevel,
        test_module="chip_top_tb",
        plusargs=[],
        waves=True,
    )


if __name__ == "__main__":
    chip_top_runner()
