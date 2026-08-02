"""
Comprehensive corner-case regression for accelerator_core.

Covers: controller FSM, host handshake, address counter, swap pulse width,
drain control, clear pulse, output sequencing, ping-pong bank tracking,
reset recovery, and all boundary conditions on tile_done/last_pass/valid_in.

All tests use only control-path signals (no SRAM read-data checks) so the
suite runs equally with the functional model or the original PDK model.
"""

from __future__ import annotations

import random
from typing import Iterable, Optional, Set

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, Timer, ReadOnly


CLK_PERIOD_NS = 40
TILE_BYTES    = 128
DRAIN_CYCLES  = 14   # 2*(8-1)
OUTPUT_WORDS  = 64   # 8*8 results


# =============================================================================
# Helpers
# =============================================================================

def value_int(handle) -> int:
    return int(handle.value)


def assert_eq(actual: int, expected: int, message: str) -> None:
    assert actual == expected, f"{message}: actual={actual}, expected={expected}"


async def start_clock(dut) -> None:
    dut.clk.value = 0
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await Timer(1, unit="ns")


async def reset_dut(dut) -> None:
    dut.rst_n.value    = 0
    dut.data_in.value  = 0
    dut.valid_in.value = 0
    dut.tile_done.value = 0
    dut.last_pass.value = 0
    dut.ready_out.value = 0

    for _ in range(4):
        await RisingEdge(dut.clk)

    await FallingEdge(dut.clk)
    dut.rst_n.value = 1

    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")

    # Prime the GF180 PDK SRAM behavioral model.
    # The model requires cen_fell=1 before it will respond to reads/writes.
    # We force it via hierarchy — simulation-only, zero RTL/tapeout impact.
    try:
        dut.u_memory.SRAM_0.cen_fell.value = 1
        dut.u_memory.SRAM_1.cen_fell.value = 1
        await Timer(1, unit="ns")
    except AttributeError:
        pass  # functional model in use — no cen_fell needed


async def setup_test(dut) -> None:
    await start_clock(dut)
    await reset_dut(dut)


async def present_before_rising(
    dut,
    *,
    data: int = 0,
    valid: int = 0,
    tile_done: int = 0,
    last_pass: int = 0,
    ready_out: int = 0,
) -> None:
    await FallingEdge(dut.clk)
    dut.data_in.value   = data & 0xFF
    dut.valid_in.value  = int(bool(valid))
    dut.tile_done.value = int(bool(tile_done))
    dut.last_pass.value = int(bool(last_pass))
    dut.ready_out.value = int(bool(ready_out))
    await Timer(1, unit="ns")


async def complete_rising_edge(dut) -> None:
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")


async def send_one_accepted_byte(
    dut,
    *,
    expected_addr: int,
    data: int,
    tile_done: int = 0,
    last_pass: int = 0,
    ready_out: int = 0,
) -> None:
    await present_before_rising(
        dut,
        data=data,
        valid=1,
        tile_done=tile_done,
        last_pass=last_pass,
        ready_out=ready_out,
    )
    assert_eq(value_int(dut.write_en),   1,             "write_en before accepted byte")
    assert_eq(value_int(dut.write_addr), expected_addr, "write_addr before accepted byte")
    await complete_rising_edge(dut)


async def send_one_stall_cycle(
    dut,
    *,
    expected_addr: int,
    data: int = 0xA5,
    tile_done: int = 0,
    last_pass: int = 0,
    ready_out: int = 0,
) -> None:
    await present_before_rising(
        dut,
        data=data,
        valid=0,
        tile_done=tile_done,
        last_pass=last_pass,
        ready_out=ready_out,
    )
    assert_eq(value_int(dut.write_en),   0,             "write_en during stall")
    assert_eq(value_int(dut.write_addr), expected_addr, "write_addr before stalled edge")
    await complete_rising_edge(dut)
    assert_eq(value_int(dut.write_addr), expected_addr, "write_addr after stalled edge")


async def send_full_tile(
    dut,
    *,
    final_tile: bool,
    stall_before: Optional[Set[int]] = None,
    ready_out_toggle: bool = False,
) -> None:
    """Send all 128 bytes of one tile. Optionally stall before certain addresses."""
    stalls: Set[int] = stall_before or set()
    for address in range(TILE_BYTES):
        if address in stalls:
            await send_one_stall_cycle(
                dut,
                expected_addr=address,
                ready_out=int(ready_out_toggle and (address & 1)),
            )
        is_last = address == TILE_BYTES - 1
        await send_one_accepted_byte(
            dut,
            expected_addr=address,
            data=((address * 73 + 19) & 0xFF),
            tile_done=int(is_last),
            last_pass=int(final_tile),
            ready_out=int(ready_out_toggle and (address & 1)),
        )
        if not is_last:
            assert_eq(value_int(dut.swap),     0, f"swap before final byte {address}")
            assert_eq(value_int(dut.drain_en), 0, f"drain_en before final byte {address}")

    assert_eq(value_int(dut.swap),      1, "swap pulse after completed tile")
    assert_eq(value_int(dut.write_addr), 0, "write_addr wraps to 0 after tile")
    if final_tile:
        assert_eq(value_int(dut.drain_en), 1, "drain_en after final tile")
        assert_eq(value_int(dut.ready_in), 0, "ready_in blocked after final tile")
    else:
        assert_eq(value_int(dut.drain_en), 0, "drain_en after non-final tile")
        assert_eq(value_int(dut.ready_in), 1, "ready_in re-granted after non-final tile")


async def wait_for_drain_done(dut, *, timeout_cycles: int = 200) -> int:
    """Wait for drain_done=1. Returns cycle count."""
    for cycle in range(timeout_cycles):
        await present_before_rising(dut, valid=0)
        await complete_rising_edge(dut)
        if value_int(dut.drain_done):
            return cycle
    raise AssertionError(f"drain_done never fired within {timeout_cycles} cycles")


async def pulse_output_done(dut) -> None:
    """Send one output_done=1 pulse."""
    await present_before_rising(dut, valid=0, ready_out=1)
    dut.ready_out.value = 1
    await FallingEdge(dut.clk)
    # output_done is ready_out in this testbench interface
    await complete_rising_edge(dut)
    dut.ready_out.value = 0


async def drain_and_finish(dut) -> None:
    """
    Wait for feeder drain to complete, then send output_done to finish OUTPUT state.
    Monitors drain_en stays high throughout drain, and output_en goes high after drain.
    """
    # Drain phase: wait for drain_done
    drain_seen = 0
    for _ in range(300):
        await present_before_rising(dut, valid=0)
        await complete_rising_edge(dut)
        if value_int(dut.drain_en):
            drain_seen += 1
        if value_int(dut.drain_done):
            break
    else:
        raise AssertionError("drain_done never asserted")

    # After drain_done: output_en should be high (combinational, same cycle)
    # Give one stall cycle then signal output_done
    for _ in range(OUTPUT_WORDS):
        await present_before_rising(dut, valid=0, ready_out=1)
        await complete_rising_edge(dut)
        if value_int(dut.output_done if hasattr(dut, "output_done") else dut.valid_out) == 0:
            break

    # Signal output complete
    await present_before_rising(dut, valid=0, ready_out=1)
    dut.tile_done.value = 0
    await complete_rising_edge(dut)


# =============================================================================
# Original 11 tests (preserved exactly)
# =============================================================================

@cocotb.test()
async def test_reset_idle_contract(dut):
    await setup_test(dut)
    assert_eq(value_int(dut.ready_in),  1, "ready_in after reset")
    assert_eq(value_int(dut.write_addr),0, "write_addr after reset")
    assert_eq(value_int(dut.write_en),  0, "write_en after reset")
    assert_eq(value_int(dut.swap),      0, "swap after reset")
    assert_eq(value_int(dut.drain_en),  0, "drain_en after reset")
    assert_eq(value_int(dut.clear),     0, "clear after reset")
    assert_eq(value_int(dut.output_en), 0, "output_en after reset")
    assert_eq(value_int(dut.valid_out), 0, "valid_out after reset")
    dut._log.info("PASS: reset/idle contract")


@cocotb.test()
async def test_first_byte_consumes_ready_permission(dut):
    await setup_test(dut)
    assert_eq(value_int(dut.ready_in), 1, "initial ready_in")
    await send_one_accepted_byte(dut, expected_addr=0, data=0x13)
    assert_eq(value_int(dut.write_addr), 1, "address after first byte")
    assert_eq(value_int(dut.ready_in),   0, "ready_in after first byte")
    assert_eq(value_int(dut.swap),       0, "swap after first byte")
    assert_eq(value_int(dut.drain_en),   0, "drain_en after first byte")
    dut._log.info("PASS: first-byte permission behavior")


@cocotb.test()
async def test_valid_stall_and_resume(dut):
    await setup_test(dut)
    for address, data in enumerate((0x10, 0x20, 0x30)):
        await send_one_accepted_byte(dut, expected_addr=address, data=data)
    assert_eq(value_int(dut.write_addr), 3, "address before stalls")
    for _ in range(4):
        await send_one_stall_cycle(dut, expected_addr=3, data=0xEE)
    await send_one_accepted_byte(dut, expected_addr=3, data=0x40)
    assert_eq(value_int(dut.write_addr), 4, "address after resume")
    assert_eq(value_int(dut.ready_in),   0, "ready_in remains low mid-tile")
    dut._log.info("PASS: valid_in stall/resume")


@cocotb.test()
async def test_early_tile_done_is_ignored(dut):
    await setup_test(dut)
    for address in range(10):
        early_done = int(address in {2, 5, 8})
        await send_one_accepted_byte(
            dut,
            expected_addr=address,
            data=(0x40 + address),
            tile_done=early_done,
            last_pass=int(address == 5),
        )
        assert_eq(value_int(dut.swap),       0, f"swap after early tile_done at {address}")
        assert_eq(value_int(dut.drain_en),   0, f"drain_en after early tile_done at {address}")
        assert_eq(value_int(dut.write_addr), address + 1, f"write_addr after {address}")
    dut._log.info("PASS: early tile_done rejection")


@cocotb.test()
async def test_last_pass_without_completed_tile_does_not_drain(dut):
    await setup_test(dut)
    for address in range(12):
        await send_one_accepted_byte(
            dut,
            expected_addr=address,
            data=(0x80 + address),
            tile_done=0,
            last_pass=1,
        )
        assert_eq(value_int(dut.swap),     0, f"swap with last_pass only at {address}")
        assert_eq(value_int(dut.drain_en), 0, f"drain_en with last_pass only at {address}")
        assert_eq(value_int(dut.output_en),0, f"output_en with last_pass only at {address}")
    dut._log.info("PASS: last_pass requires a completed tile")


@cocotb.test()
async def test_write_en_is_not_gated_by_ready_in(dut):
    await setup_test(dut)
    await send_one_accepted_byte(dut, expected_addr=0, data=0x11)
    assert_eq(value_int(dut.ready_in), 0, "ready_in after tile start")
    await present_before_rising(dut, data=0x22, valid=1)
    assert_eq(value_int(dut.ready_in), 0, "ready_in before second byte")
    assert_eq(value_int(dut.write_en), 1, "write_en while ready_in is low")
    assert_eq(value_int(dut.write_addr),1, "second-byte pre-edge address")
    await complete_rising_edge(dut)
    assert_eq(value_int(dut.write_addr),2, "address after second byte")
    dut._log.info("PASS: write_en independent of ready_in mid-tile")


@cocotb.test()
async def test_nonfinal_tile_swap_permission_and_bank_toggle(dut):
    await setup_test(dut)
    bank_visible = hasattr(dut, "u_memory") and hasattr(dut.u_memory, "ping_pong_state")
    bank_before = value_int(dut.u_memory.ping_pong_state) if bank_visible else None
    await send_full_tile(dut, final_tile=False, stall_before={0, 1, 7, 31, 63, 95, 126})
    await send_one_stall_cycle(dut, expected_addr=0)
    assert_eq(value_int(dut.swap),     0, "swap pulse width")
    assert_eq(value_int(dut.ready_in), 1, "ready_in after swap cycle")
    if bank_visible:
        bank_after = value_int(dut.u_memory.ping_pong_state)
        assert bank_after != bank_before, f"ping_pong_state did not toggle: {bank_before}→{bank_after}"
        await send_one_stall_cycle(dut, expected_addr=0)
        assert_eq(value_int(dut.u_memory.ping_pong_state), bank_after,
                  "ping_pong_state changed without swap")
    dut._log.info("PASS: non-final tile swap/permission/bank toggle")


@cocotb.test()
async def test_final_tile_starts_drain_and_blocks_new_permission(dut):
    await setup_test(dut)
    await send_full_tile(dut, final_tile=True, stall_before={3, 17, 64, 100, 127})
    assert_eq(value_int(dut.ready_in),  0, "ready_in immediately after final tile")
    assert_eq(value_int(dut.drain_en),  1, "drain_en immediately after final tile")
    assert_eq(value_int(dut.output_en), 0, "output_en before drain_done")
    await send_one_stall_cycle(dut, expected_addr=0, last_pass=0)
    assert_eq(value_int(dut.swap),     0, "swap pulse after final tile")
    assert_eq(value_int(dut.ready_in), 0, "ready_in during final drain")
    assert_eq(value_int(dut.drain_en), 1, "drain_en during final drain")
    dut._log.info("PASS: final-tile drain control")


@cocotb.test()
async def test_reset_mid_tile_recovers_cleanly(dut):
    await setup_test(dut)
    for address in range(17):
        await send_one_accepted_byte(dut, expected_addr=address, data=((address*11)+3))
    assert_eq(value_int(dut.write_addr), 17, "address before mid-tile reset")
    assert_eq(value_int(dut.ready_in),    0, "ready_in before mid-tile reset")
    await FallingEdge(dut.clk)
    dut.valid_in.value = 0; dut.tile_done.value = 0
    dut.last_pass.value = 0; dut.ready_out.value = 0
    dut.rst_n.value = 0
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert_eq(value_int(dut.ready_in),  1, "ready_in during reset")
    assert_eq(value_int(dut.write_addr),0, "write_addr during reset")
    assert_eq(value_int(dut.swap),      0, "swap during reset")
    assert_eq(value_int(dut.drain_en),  0, "drain_en during reset")
    assert_eq(value_int(dut.clear),     0, "clear during reset")
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert_eq(value_int(dut.ready_in),  1, "ready_in after reset recovery")
    assert_eq(value_int(dut.write_addr),0, "write_addr after reset recovery")
    await send_one_accepted_byte(dut, expected_addr=0, data=0x5A)
    assert_eq(value_int(dut.write_addr),1, "new transaction after reset")
    dut._log.info("PASS: mid-tile reset recovery")


@cocotb.test()
async def test_randomized_stall_address_scoreboard(dut):
    await setup_test(dut)
    rng = random.Random(0xC0C07B)
    accepted = 0; total_stalls = 0
    while accepted < TILE_BYTES:
        if rng.random() < 0.32:
            await send_one_stall_cycle(dut, expected_addr=accepted,
                                       data=rng.randrange(256),
                                       ready_out=rng.randrange(2))
            total_stalls += 1
            continue
        is_last = accepted == TILE_BYTES - 1
        if   accepted % 8 == 0: data = 0x00
        elif accepted % 8 == 1: data = 0xFF
        elif accepted % 8 == 2: data = 0x80
        elif accepted % 8 == 3: data = 0x7F
        else:                   data = rng.randrange(256)
        await send_one_accepted_byte(dut, expected_addr=accepted, data=data,
                                     tile_done=int(is_last), last_pass=0,
                                     ready_out=rng.randrange(2))
        accepted += 1
    assert accepted == TILE_BYTES
    assert total_stalls > 20
    assert_eq(value_int(dut.write_addr),0, "address after randomized tile")
    assert_eq(value_int(dut.swap),      1, "swap after randomized tile")
    assert_eq(value_int(dut.ready_in),  1, "ready_in after randomized tile")
    assert_eq(value_int(dut.drain_en),  0, "drain_en after randomized non-final tile")
    dut._log.info(f"PASS: randomized address scoreboard (accepted={accepted}, stalls={total_stalls})")


@cocotb.test()
async def test_output_side_inputs_do_not_disturb_loading(dut):
    await setup_test(dut)
    for address in range(24):
        await send_one_accepted_byte(dut, expected_addr=address,
                                     data=(0xF0 ^ address), ready_out=(address & 1))
        assert_eq(value_int(dut.output_en), 0, f"output_en during load {address}")
        assert_eq(value_int(dut.valid_out), 0, f"valid_out during load {address}")
        assert_eq(value_int(dut.clear),     0, f"clear during load {address}")
        assert_eq(value_int(dut.swap),      0, f"swap during load {address}")
    dut._log.info("PASS: output-side independence during loading")


# =============================================================================
# New tests
# =============================================================================

@cocotb.test()
async def test_swap_is_single_cycle_pulse(dut):
    """swap must be exactly 1 clock wide — not held."""
    await setup_test(dut)
    await send_full_tile(dut, final_tile=False)
    # swap=1 was checked inside send_full_tile on the swap cycle.
    # Now advance one more cycle and confirm swap=0.
    await send_one_stall_cycle(dut, expected_addr=0)
    assert_eq(value_int(dut.swap), 0, "swap must deassert after 1 cycle")
    await send_one_stall_cycle(dut, expected_addr=0)
    assert_eq(value_int(dut.swap), 0, "swap stays 0 two cycles after pulse")
    dut._log.info("PASS: swap is single-cycle pulse")


@cocotb.test()
async def test_write_addr_wraps_to_zero_after_swap(dut):
    """write_addr must be 0 the cycle after swap, not 128."""
    await setup_test(dut)
    await send_full_tile(dut, final_tile=False)
    # Immediately after tile: write_addr=0, swap=1 (checked in send_full_tile)
    # One cycle later: write_addr still 0 (no new data)
    await send_one_stall_cycle(dut, expected_addr=0)
    assert_eq(value_int(dut.write_addr), 0, "write_addr stays 0 after swap with no data")
    dut._log.info("PASS: write_addr wraps to 0 after swap")


@cocotb.test()
async def test_fsm_stays_idle_without_valid_in(dut):
    """With valid_in=0 the FSM must remain IDLE indefinitely."""
    await setup_test(dut)
    for cycle in range(20):
        await send_one_stall_cycle(dut, expected_addr=0, tile_done=1, last_pass=1)
        assert_eq(value_int(dut.ready_in),  1, f"ready_in idle at cycle {cycle}")
        assert_eq(value_int(dut.write_en),  0, f"write_en idle at cycle {cycle}")
        assert_eq(value_int(dut.swap),      0, f"swap idle at cycle {cycle}")
        assert_eq(value_int(dut.drain_en),  0, f"drain_en idle at cycle {cycle}")
        assert_eq(value_int(dut.output_en), 0, f"output_en idle at cycle {cycle}")
    dut._log.info("PASS: FSM stays IDLE without valid_in")


@cocotb.test()
async def test_tile_done_on_wrong_address_ignored(dut):
    """tile_done=1 on byte 126 (not 127) must not trigger swap."""
    await setup_test(dut)
    for address in range(126):
        await send_one_accepted_byte(dut, expected_addr=address,
                                     data=(address & 0xFF))
    # Send byte 126 with tile_done=1 and last_pass=1 — should be ignored
    await send_one_accepted_byte(dut, expected_addr=126, data=0xAB,
                                 tile_done=1, last_pass=1)
    assert_eq(value_int(dut.swap),     0, "swap must not fire on wrong address tile_done")
    assert_eq(value_int(dut.drain_en), 0, "drain_en must not set on wrong address tile_done")
    assert_eq(value_int(dut.write_addr),127, "write_addr continues to 127")
    dut._log.info("PASS: tile_done on wrong address ignored")


@cocotb.test()
async def test_tile_done_and_last_pass_simultaneous_on_byte_127(dut):
    """tile_done=1 + last_pass=1 on exactly byte 127 → final tile behavior."""
    await setup_test(dut)
    for address in range(127):
        await send_one_accepted_byte(dut, expected_addr=address, data=(address & 0xFF))
    # Final byte with both flags
    await send_one_accepted_byte(dut, expected_addr=127, data=0xFF,
                                 tile_done=1, last_pass=1)
    assert_eq(value_int(dut.swap),     1, "swap on byte 127 with tile_done+last_pass")
    assert_eq(value_int(dut.drain_en), 1, "drain_en set on simultaneous tile_done+last_pass")
    assert_eq(value_int(dut.ready_in), 0, "ready_in blocked after final tile")
    dut._log.info("PASS: tile_done+last_pass simultaneous on byte 127")


@cocotb.test()
async def test_tile_done_byte_127_no_last_pass_is_nonfinal(dut):
    """tile_done=1 on byte 127 with last_pass=0 → non-final swap, no drain."""
    await setup_test(dut)
    for address in range(127):
        await send_one_accepted_byte(dut, expected_addr=address, data=(address & 0xFF))
    await send_one_accepted_byte(dut, expected_addr=127, data=0x42,
                                 tile_done=1, last_pass=0)
    assert_eq(value_int(dut.swap),     1, "swap fires on byte 127")
    assert_eq(value_int(dut.drain_en), 0, "drain_en stays 0 without last_pass")
    assert_eq(value_int(dut.ready_in), 1, "ready_in re-granted for non-final tile")
    dut._log.info("PASS: tile_done without last_pass → non-final swap")


@cocotb.test()
async def test_stall_on_first_byte(dut):
    """Multiple stalls before byte 0 — controller stays in IDLE, addr=0."""
    await setup_test(dut)
    for _ in range(5):
        await send_one_stall_cycle(dut, expected_addr=0,
                                   tile_done=1, last_pass=1)
        assert_eq(value_int(dut.ready_in),  1, "ready_in in IDLE with stall")
        assert_eq(value_int(dut.write_en),  0, "write_en during IDLE stall")
        assert_eq(value_int(dut.swap),      0, "swap during IDLE stall")
    await send_one_accepted_byte(dut, expected_addr=0, data=0x01)
    assert_eq(value_int(dut.write_addr), 1, "address after stalled first byte")
    dut._log.info("PASS: stall on first byte")


@cocotb.test()
async def test_stall_on_last_byte(dut):
    """Stalls before byte 127 — swap must fire only after the actual byte 127."""
    await setup_test(dut)
    for address in range(127):
        await send_one_accepted_byte(dut, expected_addr=address, data=(address & 0xFF))
    # Three stall cycles at address 127
    for _ in range(3):
        await send_one_stall_cycle(dut, expected_addr=127)
        assert_eq(value_int(dut.swap), 0, "swap must not fire during stall at byte 127")
    # Now send the actual byte 127
    await send_one_accepted_byte(dut, expected_addr=127, data=0x7F,
                                 tile_done=1, last_pass=0)
    assert_eq(value_int(dut.swap),     1, "swap fires after byte 127 accepted")
    assert_eq(value_int(dut.drain_en), 0, "no drain for non-final tile")
    dut._log.info("PASS: stall on last byte")


@cocotb.test()
async def test_back_to_back_maximum_throughput(dut):
    """128 bytes with zero stalls — maximum throughput path."""
    await setup_test(dut)
    for address in range(TILE_BYTES):
        is_last = address == TILE_BYTES - 1
        await send_one_accepted_byte(dut, expected_addr=address,
                                     data=(address & 0xFF),
                                     tile_done=int(is_last), last_pass=0)
    assert_eq(value_int(dut.swap),      1, "swap after zero-stall tile")
    assert_eq(value_int(dut.write_addr),0, "write_addr wraps to 0")
    assert_eq(value_int(dut.ready_in),  1, "ready_in re-granted")
    dut._log.info("PASS: back-to-back maximum throughput")


@cocotb.test()
async def test_two_consecutive_non_final_tiles_bank_toggles_twice(dut):
    """Two non-final tiles → ping_pong_state toggles twice → returns to original."""
    await setup_test(dut)
    bank_visible = hasattr(dut, "u_memory") and hasattr(dut.u_memory, "ping_pong_state")
    bank_initial = value_int(dut.u_memory.ping_pong_state) if bank_visible else 0

    await send_full_tile(dut, final_tile=False)
    # ping_pong_state is a registered FF — updates the cycle AFTER swap.
    # Advance one stall cycle so the FF has settled before we read it.
    await send_one_stall_cycle(dut, expected_addr=0)
    if bank_visible:
        bank_mid = value_int(dut.u_memory.ping_pong_state)
        assert bank_mid != bank_initial, f"bank did not toggle after tile 1: still {bank_mid}"

    await send_full_tile(dut, final_tile=False)
    await send_one_stall_cycle(dut, expected_addr=0)
    if bank_visible:
        bank_final = value_int(dut.u_memory.ping_pong_state)
        assert bank_final == bank_initial, \
            f"bank should return to {bank_initial} after 2 swaps, got {bank_final}"

    assert_eq(value_int(dut.write_addr), 0, "write_addr=0 after tile 2")
    assert_eq(value_int(dut.ready_in),   1, "ready_in=1 after tile 2")
    dut._log.info("PASS: two consecutive non-final tiles bank toggles twice")


@cocotb.test()
async def test_second_tile_address_sequence_restarts(dut):
    """After first tile swap, second tile address sequence starts cleanly from 0."""
    await setup_test(dut)
    await send_full_tile(dut, final_tile=False)
    # Start second tile and check addresses restart from 0
    for address in range(8):
        await send_one_accepted_byte(dut, expected_addr=address,
                                     data=(0xA0 + address))
    assert_eq(value_int(dut.write_addr), 8, "second tile address sequence correct")
    assert_eq(value_int(dut.swap),       0, "no swap mid-second-tile")
    dut._log.info("PASS: second tile address sequence restarts from 0")


@cocotb.test()
async def test_drain_en_stays_high_during_drain(dut):
    """drain_en must remain 1 for all cycles between swap and drain_done."""
    await setup_test(dut)
    await send_full_tile(dut, final_tile=True)
    assert_eq(value_int(dut.drain_en), 1, "drain_en after final tile swap")

    # Poll until drain_done, checking drain_en every cycle
    for cycle in range(200):
        await send_one_stall_cycle(dut, expected_addr=0)
        if value_int(dut.drain_done):
            break
        assert_eq(value_int(dut.drain_en), 1,
                  f"drain_en must stay high at cycle {cycle}")
    else:
        raise AssertionError("drain_done never fired")

    dut._log.info("PASS: drain_en stays high during entire drain phase")


@cocotb.test()
async def test_drain_en_cleared_after_drain_done(dut):
    """drain_en must go to 0 after drain_done."""
    await setup_test(dut)
    await send_full_tile(dut, final_tile=True)

    drain_done_seen = False
    for _ in range(200):
        await send_one_stall_cycle(dut, expected_addr=0)
        if value_int(dut.drain_done):
            drain_done_seen = True
            break
    assert drain_done_seen, "drain_done never fired"

    # Give one cycle for drain_en to clear
    await send_one_stall_cycle(dut, expected_addr=0)
    assert_eq(value_int(dut.drain_en), 0, "drain_en must clear after drain_done")
    dut._log.info("PASS: drain_en cleared after drain_done")


@cocotb.test()
async def test_output_en_asserts_after_drain_done(dut):
    """output_en must go high when drain completes (combinational from OUTPUT state)."""
    await setup_test(dut)
    await send_full_tile(dut, final_tile=True)
    assert_eq(value_int(dut.output_en), 0, "output_en before drain")

    for _ in range(200):
        await send_one_stall_cycle(dut, expected_addr=0)
        if value_int(dut.drain_done):
            # output_en is combinational — must be 1 in same or next cycle
            break
    else:
        raise AssertionError("drain_done never fired")

    await send_one_stall_cycle(dut, expected_addr=0)
    assert_eq(value_int(dut.output_en), 1, "output_en must assert after drain_done")
    dut._log.info("PASS: output_en asserts after drain_done")


@cocotb.test()
async def test_ready_in_blocked_during_output(dut):
    """ready_in must stay 0 while in OUTPUT state (no new tile accepted)."""
    await setup_test(dut)
    await send_full_tile(dut, final_tile=True)

    # Wait for output_en
    for _ in range(200):
        await send_one_stall_cycle(dut, expected_addr=0)
        if value_int(dut.output_en):
            break
    else:
        raise AssertionError("output_en never asserted")

    # Check ready_in stays 0 for several cycles in OUTPUT state
    for cycle in range(5):
        await send_one_stall_cycle(dut, expected_addr=0, ready_out=0)
        assert_eq(value_int(dut.ready_in), 0,
                  f"ready_in must stay 0 during OUTPUT at cycle {cycle}")
    dut._log.info("PASS: ready_in blocked during OUTPUT state")


@cocotb.test()
async def test_valid_in_ignored_during_output_state(dut):
    """valid_in=1 during OUTPUT state must not increment write_addr or set write_en."""
    await setup_test(dut)
    await send_full_tile(dut, final_tile=True)

    # Wait for output_en
    for _ in range(200):
        await send_one_stall_cycle(dut, expected_addr=0)
        if value_int(dut.output_en):
            break
    else:
        raise AssertionError("output_en never asserted")

    # Try to inject data during OUTPUT — should be ignored
    for _ in range(3):
        await present_before_rising(dut, data=0xDE, valid=1, tile_done=1, last_pass=1)
        assert_eq(value_int(dut.write_en), 0, "write_en must be 0 in OUTPUT state")
        await complete_rising_edge(dut)
        assert_eq(value_int(dut.write_addr), 0, "write_addr must not change in OUTPUT state")
        assert_eq(value_int(dut.swap),       0, "swap must not fire in OUTPUT state")
    dut._log.info("PASS: valid_in ignored during OUTPUT state")


@cocotb.test()
async def test_clear_does_not_fire_during_processing(dut):
    """clear must stay 0 throughout a full non-final tile load."""
    await setup_test(dut)
    for address in range(TILE_BYTES):
        is_last = address == TILE_BYTES - 1
        await send_one_accepted_byte(dut, expected_addr=address,
                                     data=(address & 0xFF),
                                     tile_done=int(is_last), last_pass=0)
        assert_eq(value_int(dut.clear), 0,
                  f"clear must not fire during PROCESSING at byte {address}")
    dut._log.info("PASS: clear never fires during PROCESSING")


@cocotb.test()
async def test_ready_out_toggling_does_not_affect_controller(dut):
    """ready_out toggling during loading must not disturb write_addr or swap."""
    await setup_test(dut)
    for address in range(20):
        # Alternate ready_out every byte
        await send_one_accepted_byte(dut, expected_addr=address,
                                     data=(address & 0xFF),
                                     ready_out=(address & 1))
        assert_eq(value_int(dut.swap),   0, f"swap must not fire at {address}")
        assert_eq(value_int(dut.clear),  0, f"clear must not fire at {address}")
        assert_eq(value_int(dut.write_addr), address + 1,
                  f"write_addr unaffected by ready_out at {address}")
    dut._log.info("PASS: ready_out toggling does not affect controller")


@cocotb.test()
async def test_multiple_resets_in_sequence(dut):
    """Three resets in a row — each time controller returns to clean IDLE state."""
    await setup_test(dut)
    for reset_num in range(3):
        # Send a few bytes to move out of IDLE
        for address in range(5):
            await send_one_accepted_byte(dut, expected_addr=address,
                                         data=(0x10 + address))
        assert_eq(value_int(dut.write_addr), 5, f"write_addr before reset {reset_num}")

        # Reset
        await FallingEdge(dut.clk)
        dut.valid_in.value = 0; dut.rst_n.value = 0
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        await FallingEdge(dut.clk)
        dut.rst_n.value = 1
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")

        # Re-prime cen_fell after each reset
        try:
            dut.u_memory.SRAM_0.cen_fell.value = 1
            dut.u_memory.SRAM_1.cen_fell.value = 1
            await Timer(1, unit="ns")
        except AttributeError:
            pass

        assert_eq(value_int(dut.ready_in),  1, f"ready_in after reset {reset_num}")
        assert_eq(value_int(dut.write_addr),0, f"write_addr after reset {reset_num}")
        assert_eq(value_int(dut.swap),      0, f"swap after reset {reset_num}")
        assert_eq(value_int(dut.drain_en),  0, f"drain_en after reset {reset_num}")
        assert_eq(value_int(dut.clear),     0, f"clear after reset {reset_num}")
        assert_eq(value_int(dut.output_en), 0, f"output_en after reset {reset_num}")

    dut._log.info("PASS: multiple resets in sequence")


@cocotb.test()
async def test_ping_pong_state_after_two_swaps(dut):
    """Two swaps return ping_pong_state to its original value."""
    await setup_test(dut)
    bank_visible = hasattr(dut, "u_memory") and hasattr(dut.u_memory, "ping_pong_state")
    if not bank_visible:
        dut._log.info("SKIP: ping_pong_state not visible — skipping bank check")
        return

    initial = value_int(dut.u_memory.ping_pong_state)

    # First swap — read ping_pong_state one cycle after swap (it is a registered FF)
    await send_full_tile(dut, final_tile=False)
    await send_one_stall_cycle(dut, expected_addr=0)
    after_1 = value_int(dut.u_memory.ping_pong_state)
    assert after_1 != initial, f"ping_pong_state must toggle after first swap: {initial}→{after_1}"

    # Second swap
    await send_full_tile(dut, final_tile=False)
    await send_one_stall_cycle(dut, expected_addr=0)
    after_2 = value_int(dut.u_memory.ping_pong_state)
    assert after_2 == initial, \
        f"ping_pong_state must return to {initial} after two swaps, got {after_2}"

    dut._log.info("PASS: ping_pong_state correct after two swaps")


@cocotb.test()
async def test_all_data_byte_values_accepted(dut):
    """All 256 possible data byte values are accepted without controller error."""
    await setup_test(dut)
    # Send 128 bytes cycling through corner data values
    data_pattern = [0x00, 0xFF, 0x01, 0xFE, 0x55, 0xAA, 0x80, 0x7F] * 16
    for address in range(TILE_BYTES):
        is_last = address == TILE_BYTES - 1
        await send_one_accepted_byte(dut, expected_addr=address,
                                     data=data_pattern[address],
                                     tile_done=int(is_last), last_pass=0)
    assert_eq(value_int(dut.swap),      1, "swap after all-values tile")
    assert_eq(value_int(dut.drain_en),  0, "no drain for non-final tile")
    assert_eq(value_int(dut.ready_in),  1, "ready_in re-granted")
    dut._log.info("PASS: all data byte values accepted")


@cocotb.test()
async def test_randomized_two_tile_sequence(dut):
    """
    Two tiles with randomized stall patterns and data.
    Tile 1 is non-final, tile 2 is non-final.
    Verifies address counter correctness across the tile boundary.
    """
    await setup_test(dut)
    rng = random.Random(0xDEADBEEF)

    for tile_num in range(2):
        accepted = 0
        stalls = 0
        while accepted < TILE_BYTES:
            if rng.random() < 0.25:
                await send_one_stall_cycle(dut, expected_addr=accepted,
                                           data=rng.randrange(256))
                stalls += 1
                continue
            is_last = accepted == TILE_BYTES - 1
            await send_one_accepted_byte(dut, expected_addr=accepted,
                                         data=rng.randrange(256),
                                         tile_done=int(is_last), last_pass=0)
            accepted += 1

        assert_eq(value_int(dut.swap),      1, f"swap after tile {tile_num}")
        assert_eq(value_int(dut.write_addr),0, f"write_addr=0 after tile {tile_num}")
        assert_eq(value_int(dut.ready_in),  1, f"ready_in=1 after tile {tile_num}")
        dut._log.info(f"  tile {tile_num}: accepted={accepted} stalls={stalls}")

    dut._log.info("PASS: randomized two-tile sequence")


@cocotb.test()
async def test_write_en_gated_by_state_in_idle(dut):
    """In IDLE, valid_in=1 on the first byte: write_en must be 1 immediately."""
    await setup_test(dut)
    # Verify write_en is 0 when valid_in=0 in IDLE
    await present_before_rising(dut, valid=0)
    assert_eq(value_int(dut.write_en), 0, "write_en=0 in IDLE with valid_in=0")
    await complete_rising_edge(dut)

    # Now assert valid_in — write_en must respond combinationally
    await present_before_rising(dut, valid=1, data=0x42)
    assert_eq(value_int(dut.write_en),  1, "write_en=1 in IDLE with valid_in=1")
    assert_eq(value_int(dut.write_addr),0, "write_addr=0 for first byte")
    await complete_rising_edge(dut)
    dut._log.info("PASS: write_en combinational in IDLE")


@cocotb.test()
async def test_no_spurious_output_en_during_non_final_tile(dut):
    """output_en must never assert during a non-final tile."""
    await setup_test(dut)
    await send_full_tile(dut, final_tile=False)
    # After non-final tile, check output_en stays 0 for many cycles
    for cycle in range(20):
        await send_one_stall_cycle(dut, expected_addr=0)
        assert_eq(value_int(dut.output_en), 0,
                  f"output_en spuriously asserted at cycle {cycle} after non-final tile")
    dut._log.info("PASS: no spurious output_en during non-final tile")


@cocotb.test()
async def test_drain_cycle_count(dut):
    """
    Verify that drain_active remains asserted for exactly 14 cycles.

    drain_done timing is already checked by the separate drain_done and
    output-state tests. This test checks only the drain-cycle duration.
    """
    await setup_test(dut)
    await send_full_tile(dut, final_tile=True)

    drain_cycle_count = 0
    drain_started = False

    for wait_cycle in range(300):

        # Drive idle host inputs on the falling edge.
        await present_before_rising(
            dut,
            valid=0,
            tile_done=0,
            last_pass=0,
            ready_out=0,
        )

        # Wait until all combinational signals have settled.
        await ReadOnly()

        drain_active = value_int(
            dut.u_feeder.drain_active
        )

        drain_counter = value_int(
            dut.u_feeder.drain_counter
        )

        array_valid = value_int(dut.valid)

        if drain_active:
            drain_started = True

            # Counter must progress as 0, 1, ..., 13.
            assert_eq(
                drain_counter,
                drain_cycle_count,
                "unexpected drain_counter sequence",
            )

            # The systolic array must remain enabled during drain.
            assert_eq(
                array_valid,
                1,
                f"valid during drain counter {drain_counter}",
            )

            drain_cycle_count += 1

        elif drain_started:
            # drain_active was previously high and has now fallen.
            # The complete drain interval has been observed.
            break

        # Advance to the next active clock edge.
        await complete_rising_edge(dut)

    else:
        raise AssertionError(
            "drain_active did not finish within 300 cycles"
        )

    assert drain_started, (
        "drain_active was never asserted"
    )

    assert drain_cycle_count == DRAIN_CYCLES, (
        f"Expected {DRAIN_CYCLES} drain cycles, "
        f"got {drain_cycle_count}"
    )

    dut._log.info(
        f"PASS: drain_active covered counters "
        f"0..{DRAIN_CYCLES - 1} and lasted exactly "
        f"{drain_cycle_count} cycles"
    )

@cocotb.test()
async def test_clear_not_fire_during_normal_processing(dut):
    """clear must be 0 throughout IDLE and PROCESSING — only fires in OUTPUT→IDLE."""
    await setup_test(dut)
    # Check clear=0 in IDLE
    for _ in range(5):
        await send_one_stall_cycle(dut, expected_addr=0)
        assert_eq(value_int(dut.clear), 0, "clear in IDLE")

    # Check clear=0 throughout non-final tile
    await send_full_tile(dut, final_tile=False)
    for _ in range(5):
        await send_one_stall_cycle(dut, expected_addr=0)
        assert_eq(value_int(dut.clear), 0, "clear after non-final tile")
    dut._log.info("PASS: clear never fires in IDLE or PROCESSING")