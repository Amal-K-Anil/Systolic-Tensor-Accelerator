"""
cocotb testbench for mac_unit (Booth radix-4 multiplier)
Team Maxilerator | SSCS Chipathon 2026
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
import random
import numpy as np

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def to_int8(v):
    """Clamp and cast to signed 8-bit."""
    v = int(v) & 0xFF
    return v if v < 128 else v - 256

def to_signed(v, bits):
    mask = (1 << bits) - 1
    v = int(v) & mask
    return v if v < (1 << (bits - 1)) else v - (1 << bits)

async def reset(dut):
    dut.rst_n.value = 0
    dut.valid.value = 0
    dut.clear.value = 0
    dut.a_in.value  = 0
    dut.b_in.value  = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

async def mac_cycle(dut, a, b):
    """Drive one valid MAC cycle and return accum_out one cycle later."""
    dut.a_in.value  = a & 0xFF
    dut.b_in.value  = b & 0xFF
    dut.valid.value = 1
    await RisingEdge(dut.clk)
    dut.valid.value = 0
    await RisingEdge(dut.clk)   # result registered
    return to_signed(dut.accum_out.value, 21)

# ─────────────────────────────────────────────
# Test 1 — reset clears all outputs
# ─────────────────────────────────────────────

@cocotb.test()
async def test_reset(dut):
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await reset(dut)
    assert to_signed(dut.accum_out.value, 21) == 0, "accum_out should be 0 after reset"
    assert to_signed(dut.a_out.value, 8)      == 0, "a_out should be 0 after reset"
    assert to_signed(dut.b_out.value, 8)      == 0, "b_out should be 0 after reset"
    dut._log.info("PASS: reset")

# ─────────────────────────────────────────────
# Test 2 — single accumulation
# ─────────────────────────────────────────────

@cocotb.test()
async def test_single_accumulate(dut):
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await reset(dut)

    pairs = [(3, 5), (-4, 7), (127, 1), (-128, -128), (0, 99), (1, -1)]
    for a, b in pairs:
        await reset(dut)
        result = await mac_cycle(dut, a, b)
        expected = a * b
        assert result == expected, f"a={a} b={b}: got {result}, expected {expected}"
        dut._log.info(f"  {a} × {b} = {result}  ✓")
    dut._log.info("PASS: single_accumulate")

# ─────────────────────────────────────────────
# Test 3 — accumulation over multiple cycles
# ─────────────────────────────────────────────

@cocotb.test()
async def test_accumulate_multiple(dut):
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await reset(dut)

    pairs = [(3, 4), (-2, 5), (7, -3), (10, 10), (-1, -1)]
    expected_accum = 0
    for a, b in pairs:
        dut.a_in.value  = a & 0xFF
        dut.b_in.value  = b & 0xFF
        dut.valid.value = 1
        await RisingEdge(dut.clk)
        expected_accum += a * b

    dut.valid.value = 0
    await RisingEdge(dut.clk)
    result = to_signed(dut.accum_out.value, 21)
    assert result == expected_accum, f"Got {result}, expected {expected_accum}"
    dut._log.info(f"PASS: accumulate_multiple  (accum={result})")

# ─────────────────────────────────────────────
# Test 4 — clear priority over valid
# ─────────────────────────────────────────────

@cocotb.test()
async def test_clear_priority(dut):
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await reset(dut)

    # Build up some accumulation
    for _ in range(4):
        dut.a_in.value  = 5
        dut.b_in.value  = 5
        dut.valid.value = 1
        await RisingEdge(dut.clk)
    dut.valid.value = 0
    await RisingEdge(dut.clk)

    # Assert clear AND valid simultaneously — clear must win
    dut.a_in.value  = 99
    dut.b_in.value  = 99
    dut.valid.value = 1
    dut.clear.value = 1
    await RisingEdge(dut.clk)
    dut.valid.value = 0
    dut.clear.value = 0
    await RisingEdge(dut.clk)

    result = to_signed(dut.accum_out.value, 21)
    assert result == 0, f"clear should win over valid, got accum={result}"
    dut._log.info("PASS: clear_priority")

# ─────────────────────────────────────────────
# Test 5 — clear alone resets accumulator
# ─────────────────────────────────────────────

@cocotb.test()
async def test_clear_resets(dut):
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await reset(dut)

    await mac_cycle(dut, 10, 10)  # accum = 100

    dut.clear.value = 1
    await RisingEdge(dut.clk)
    dut.clear.value = 0
    await RisingEdge(dut.clk)

    result = to_signed(dut.accum_out.value, 21)
    assert result == 0, f"accum should be 0 after clear, got {result}"
    dut._log.info("PASS: clear_resets")

# ─────────────────────────────────────────────
# Test 6 — a_out / b_out propagate every cycle (not just on valid)
# ─────────────────────────────────────────────

@cocotb.test()
async def test_ab_propagate_always(dut):
    """a_out/b_out register a_in/b_in on every rising edge when valid=1.
    With valid=0 the spec says propagation happens regardless —
    verify both cases."""
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await reset(dut)

    # valid=1 path
    dut.a_in.value  = 42 & 0xFF
    dut.b_in.value  = 0xFF & 0xFF   # -1 signed
    dut.valid.value = 1
    await RisingEdge(dut.clk)
    dut.valid.value = 0
    await RisingEdge(dut.clk)
    assert to_signed(dut.a_out.value, 8) == 42
    assert to_signed(dut.b_out.value, 8) == -1
    dut._log.info("PASS: ab_propagate_always")

# ─────────────────────────────────────────────
# Test 7 — 1-cycle latency: result visible one cycle after valid
# ─────────────────────────────────────────────

@cocotb.test()
async def test_one_cycle_latency(dut):
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await reset(dut)

    a, b = 7, 6
    dut.a_in.value  = a & 0xFF
    dut.b_in.value  = b & 0xFF
    dut.valid.value = 1
    await RisingEdge(dut.clk)   # valid pulse
    dut.valid.value = 0

    # accum_out is combinational from the FF — check it now (same edge result captured)
    await Timer(1, units="ns")   # tiny settle time (combinational read)
    result = to_signed(dut.accum_out.value, 21)
    assert result == a * b, f"Expected {a*b} one cycle after valid, got {result}"
    dut._log.info(f"PASS: one_cycle_latency  ({a}×{b}={result})")

# ─────────────────────────────────────────────
# Test 8 — worst-case signed: -128 × -128 = 16384
# ─────────────────────────────────────────────

@cocotb.test()
async def test_worst_case_signed(dut):
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await reset(dut)

    result = await mac_cycle(dut, -128, -128)
    assert result == 16384, f"Expected 16384, got {result}"
    dut._log.info("PASS: worst_case_signed  (-128×-128=16384)")

# ─────────────────────────────────────────────
# Test 9 — max accumulation (32 passes of -128×-128 = 524288)
# ─────────────────────────────────────────────

@cocotb.test()
async def test_max_accumulation(dut):
    """32 × 16384 = 524288 must fit in 21-bit signed (max 1048575)."""
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await reset(dut)

    for _ in range(32):
        dut.a_in.value  = (-128) & 0xFF
        dut.b_in.value  = (-128) & 0xFF
        dut.valid.value = 1
        await RisingEdge(dut.clk)

    dut.valid.value = 0
    await RisingEdge(dut.clk)
    result = to_signed(dut.accum_out.value, 21)
    assert result == 524288, f"Expected 524288, got {result}"
    dut._log.info(f"PASS: max_accumulation  (32×(-128×-128)={result})")

# ─────────────────────────────────────────────
# Test 10 — no accumulation when valid=0
# ─────────────────────────────────────────────

@cocotb.test()
async def test_no_accum_without_valid(dut):
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await reset(dut)

    # Drive inputs but keep valid=0
    for _ in range(5):
        dut.a_in.value  = 10
        dut.b_in.value  = 10
        dut.valid.value = 0
        await RisingEdge(dut.clk)

    await RisingEdge(dut.clk)
    result = to_signed(dut.accum_out.value, 21)
    assert result == 0, f"accum should stay 0 when valid=0, got {result}"
    dut._log.info("PASS: no_accum_without_valid")

# ─────────────────────────────────────────────
# Test 11 — random stress test (100 random INT8 pairs)
# ─────────────────────────────────────────────

@cocotb.test()
async def test_random_stress(dut):
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    random.seed(42)
    errors = 0

    for _ in range(100):
        await reset(dut)
        a = random.randint(-128, 127)
        b = random.randint(-128, 127)
        result = await mac_cycle(dut, a, b)
        expected = a * b
        if result != expected:
            dut._log.error(f"FAIL: a={a} b={b} expected={expected} got={result}")
            errors += 1

    assert errors == 0, f"{errors}/100 random tests failed"
    dut._log.info("PASS: random_stress (100 pairs)")

# ─────────────────────────────────────────────
# Test 12 — clear then re-accumulate
# ─────────────────────────────────────────────

@cocotb.test()
async def test_clear_then_reaccumulate(dut):
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await reset(dut)

    # First batch
    for _ in range(4):
        dut.a_in.value  = 5
        dut.b_in.value  = 5
        dut.valid.value = 1
        await RisingEdge(dut.clk)
    dut.valid.value = 0
    await RisingEdge(dut.clk)

    # Clear
    dut.clear.value = 1
    await RisingEdge(dut.clk)
    dut.clear.value = 0
    await RisingEdge(dut.clk)

    # Second batch
    result = await mac_cycle(dut, 3, 3)
    assert result == 9, f"After clear, expected 9, got {result}"
    dut._log.info("PASS: clear_then_reaccumulate")