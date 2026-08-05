# SPDX-FileCopyrightText: © 2025 Project Template Contributors
# SPDX-License-Identifier: Apache-2.0
#
# chip_top_tb.py
#
# cocotb testbench for chip_top (Slot A).
#
# Pad-level integration test for the whole chip -- drives/reads the actual
# input_PAD/bidir_PAD pins rather than accelerator_core's internal ports.
# This catches pin-mapping mistakes in chip_core.sv/host_interface.sv;
# the protocol logic itself is already thoroughly verified at the
# accelerator_core level (feeder/output_processor/accelerator_core
# testbenches), so scope here is intentionally narrow rather than a
# repeat of that full suite.
#
# Pad cell gate-level models specify only a 1ns PAD->Y delay for both
# cell types (bidir and input-only) -- in practice, driving data and
# valid together with just a 1ns settle was NOT sufficient (confirmed:
# produces wrong, garbage output). The actual mechanism for this gap
# isn't fully pinned down, but empirically, data must be driven and
# settled for one full clock edge BEFORE valid is asserted, and valid
# is then held for exactly one transfer edge -- holding it longer
# (while ready stays high) would cause feeder to latch the same word
# twice.
#
# Test cases:
#   1  Reset -- chip idle and ready immediately after reset
#   2  Matrix multiply -- one full computation through the real pad
#      interface, checked against a numpy golden model
#
# Run with: make TOPLEVEL=chip_top

import cocotb
import numpy as np
from cocotb.clock import Clock
from cocotb.triggers import Timer, RisingEdge
from cocotb.types import LogicArray

CLK_FREQ_MHZ = 25  # matches CLOCK_PERIOD=40ns in config.yaml

# Pin map -- input_PAD bit positions
A_VALID_BIT   = 0
A_LAST_BIT    = 1
B_VALID_BIT   = 2
B_LAST_BIT    = 3
OUT_READY_BIT = 4

# Pin map -- bidir_PAD bit positions
A_READY_BIT   = 8
B_READY_BIT   = 9
OUT_VALID_BIT = 10
OUT_LAST_BIT  = 11
NUM_BIDIR     = 12


# =========================================================================
# Setup
# =========================================================================

async def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk_PAD, 1 / CLK_FREQ_MHZ * 1000, "ns").start())

async def reset_dut(dut):
    dut.rst_n_PAD.value = 0
    dut.input_PAD.value = 0
    release_data_bus(dut)
    for _ in range(3):
        await RisingEdge(dut.clk_PAD)
    dut.rst_n_PAD.value = 1
    await RisingEdge(dut.clk_PAD)
    await Timer(1, unit="ns")


# =========================================================================
# Pad-Level Drive / Read Helpers
# =========================================================================

def drive_data_bus(dut, byte_val):
    """Drive bidir_PAD[7:0]; bits [11:8] are always chip-driven and
    left released ('z') from the host side."""
    bits = "zzzz" + f"{byte_val & 0xFF:08b}"
    dut.bidir_PAD.value = LogicArray(bits)

def release_data_bus(dut):
    """Stop driving the data bus entirely -- used once out_valid_o is
    observed high, and whenever the host has nothing to send."""
    dut.bidir_PAD.value = LogicArray("z" * NUM_BIDIR)

def read_bidir_bit(dut, bit):
    return int(dut.bidir_PAD.value[bit])

def read_data_bus(dut):
    return int(dut.bidir_PAD.value[7:0])

def set_input_bits(dut, bits):
    """Atomically set multiple input_PAD bits in one read-modify-write.
    A .value write doesn't take effect until the next delta cycle, so
    setting bits one at a time via separate calls would race -- a later
    call's "current value" read would still see the pre-earlier-call
    state and silently clobber it."""
    cur = int(dut.input_PAD.value)
    for bit, value in bits.items():
        if value:
            cur |= (1 << bit)
        else:
            cur &= ~(1 << bit)
    dut.input_PAD.value = cur

def set_input_bit(dut, bit, value):
    set_input_bits(dut, {bit: value})


# =========================================================================
# Byte-Level Transfer (Pad Interface)
# =========================================================================

async def send_a_byte(dut, byte_val, last=False, timeout=500):
    for _ in range(timeout):
        if read_bidir_bit(dut, A_READY_BIT) == 1:
            break
        await RisingEdge(dut.clk_PAD)
    else:
        assert False, "a_ready_o never went high (timeout)"

    drive_data_bus(dut, byte_val)
    await RisingEdge(dut.clk_PAD)
    await Timer(1, unit="ns")

    set_input_bits(dut, {A_VALID_BIT: 1, A_LAST_BIT: 1 if last else 0})
    await RisingEdge(dut.clk_PAD)
    set_input_bits(dut, {A_VALID_BIT: 0, A_LAST_BIT: 0})
    release_data_bus(dut)

async def send_b_byte(dut, byte_val, last=False, timeout=500):
    for _ in range(timeout):
        if read_bidir_bit(dut, B_READY_BIT) == 1:
            break
        await RisingEdge(dut.clk_PAD)
    else:
        assert False, "b_ready_o never went high (timeout)"

    drive_data_bus(dut, byte_val)
    await RisingEdge(dut.clk_PAD)
    await Timer(1, unit="ns")

    set_input_bits(dut, {B_VALID_BIT: 1, B_LAST_BIT: 1 if last else 0})
    await RisingEdge(dut.clk_PAD)
    set_input_bits(dut, {B_VALID_BIT: 0, B_LAST_BIT: 0})
    release_data_bus(dut)

async def send_matrix(dut, A, B, array_size):
    """A: (array_size, array_size), B: (array_size, array_size), single
    pass. A and B bytes are sent sequentially (never in the same cycle),
    since they share one physical data bus."""
    for v in range(array_size):
        a_col = A[:, v].tolist()
        b_row = B[v, :].tolist()
        is_final = (v == array_size - 1)
        for i in range(array_size):
            await send_a_byte(dut, a_col[i], last=(is_final and i == array_size - 1))
        for i in range(array_size):
            await send_b_byte(dut, b_row[i], last=(is_final and i == array_size - 1))

async def read_results(dut, array_size, timeout_cycles=100000):
    """Reads array_size^2 result bytes. Holds out_ready_i high
    throughout, and releases the data bus for good the first time
    out_valid_o is seen -- the host never drives it again this run."""
    n = array_size * array_size
    received = []
    set_input_bit(dut, OUT_READY_BIT, 1)
    await Timer(1, unit="ns")

    released = False
    for _ in range(timeout_cycles):
        out_valid = read_bidir_bit(dut, OUT_VALID_BIT)
        data = read_data_bus(dut) if out_valid else None

        if out_valid and not released:
            release_data_bus(dut)
            released = True

        await RisingEdge(dut.clk_PAD)
        await Timer(1, unit="ns")

        if out_valid:
            received.append(data)
        if len(received) == n:
            break
    else:
        assert False, f"timeout waiting for results (got {len(received)}/{n})"

    return received


# =========================================================================
# Golden Model
# =========================================================================

def golden_matmul(A, B, sat_max=127, sat_min=-128, shift_bits=0, data_width=8):
    C = A.astype(np.int64) @ B.astype(np.int64)
    C_shifted = C >> shift_bits
    C_clamped = np.clip(C_shifted, sat_min, sat_max)
    mask = (1 << data_width) - 1
    return (C_clamped & mask).astype(np.int64)


# =========================================================================
# Test 1 -- Reset
# =========================================================================

@cocotb.test()
async def test_reset(dut):
    """After reset, the chip must not be mid-computation: a_ready_o/
    b_ready_o high (idle, accepting), out_valid_o low."""
    await start_clock(dut)
    await reset_dut(dut)

    assert read_bidir_bit(dut, A_READY_BIT) == 1, "a_ready_o not high after reset"
    assert read_bidir_bit(dut, B_READY_BIT) == 1, "b_ready_o not high after reset"
    assert read_bidir_bit(dut, OUT_VALID_BIT) == 0, "out_valid_o not low after reset"

    cocotb.log.info("PASS test_reset: chip idle and ready after reset")


# =========================================================================
# Test 2 -- Matrix Multiply
# =========================================================================

@cocotb.test()
async def test_matrix_multiply(dut):
    """One full matrix multiply through the real pad interface."""
    await start_clock(dut)
    await reset_dut(dut)

    array_size = 8  # matches ARRAY_SIZE in this build
    np.random.seed(1)
    A = np.random.randint(-3, 4, (array_size, array_size), dtype=np.int8)
    B = np.random.randint(-3, 4, (array_size, array_size), dtype=np.int8)

    await send_matrix(dut, A, B, array_size)
    received = await read_results(dut, array_size)

    expected = golden_matmul(A, B).flatten().tolist()
    assert received == expected, f"got {received}\nexpected {expected}"

    cocotb.log.info("PASS test_matrix_multiply: correct end-to-end through real pads")
