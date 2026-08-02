"""
cocotb testbench for output_processor
Team Maxilerator | SSCS Chipathon 2026

Port convention:
  results [(ARRAY_SIZE*ARRAY_SIZE*ACCUM_WIDTH)-1:0]
      result[i][j] at bits [(i*ARRAY_SIZE+j)*ACCUM_WIDTH +: ACCUM_WIDTH]
  data_out [7:0]  — saturated INT8
  valid_out       — HIGH when output_en=1 and not finished
  output_done     — single-cycle pulse after all 64 bytes transferred
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
import numpy as np
import random

ARRAY_SIZE  = 8
ACCUM_WIDTH = 21
DATA_WIDTH  = 8
SAT_POS     =  127
SAT_NEG     = -128

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def pack_results(matrix):
    """Pack NxN int64 matrix into flat results port integer."""
    val = 0
    mask = (1 << ACCUM_WIDTH) - 1
    for i in range(ARRAY_SIZE):
        for j in range(ARRAY_SIZE):
            v = int(matrix[i][j]) & mask
            val |= v << ((i * ARRAY_SIZE + j) * ACCUM_WIDTH)
    return val

def saturate(v):
    """Python reference saturation: 21-bit signed → INT8."""
    if v > SAT_POS:
        return SAT_POS
    if v < SAT_NEG:
        return SAT_NEG
    return v

def to_signed8(v):
    v = int(v) & 0xFF
    return v if v < 128 else v - 256

async def do_reset(dut):
    dut.rst_n.value     = 0
    dut.output_en.value = 0
    dut.ready_out.value = 0
    dut.results.value   = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

async def collect_outputs(dut, matrix, ready_fn=None):
    """
    Enable output_processor and collect all ARRAY_SIZE² bytes.
    ready_fn(cycle) returns ready_out value for that cycle (default: always 1).
    Returns list of received signed bytes in row-major order.
    """
    dut.results.value   = pack_results(matrix)
    dut.output_en.value = 1
    received = []
    done_seen = False
    cycle = 0

    for _ in range(ARRAY_SIZE * ARRAY_SIZE * 4 + 10):  # timeout guard
        rdy = 1 if ready_fn is None else ready_fn(cycle)
        dut.ready_out.value = rdy

        await RisingEdge(dut.clk)
        cycle += 1

        if int(dut.output_done.value) == 1:
            done_seen = True

        if int(dut.valid_out.value) == 1 and rdy == 1:
            received.append(to_signed8(dut.data_out.value))

        if done_seen:
            break

    dut.output_en.value = 0
    dut.ready_out.value = 0
    await RisingEdge(dut.clk)
    return received, done_seen

# ─────────────────────────────────────────────
# Test 1 — reset: valid_out=0, output_done=0
# ─────────────────────────────────────────────

@cocotb.test()
async def test_reset(dut):
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await do_reset(dut)
    assert int(dut.valid_out.value)   == 0, "valid_out should be 0 after reset"
    assert int(dut.output_done.value) == 0, "output_done should be 0 after reset"
    dut._log.info("PASS: reset")

# ─────────────────────────────────────────────
# Test 2 — valid_out only HIGH when output_en=1
# ─────────────────────────────────────────────

@cocotb.test()
async def test_valid_out_gated_by_output_en(dut):
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await do_reset(dut)

    dut.results.value   = pack_results(np.ones((ARRAY_SIZE, ARRAY_SIZE), dtype=np.int64))
    dut.output_en.value = 0
    dut.ready_out.value = 1
    await RisingEdge(dut.clk)
    assert int(dut.valid_out.value) == 0, "valid_out must be 0 when output_en=0"

    dut.output_en.value = 1
    await RisingEdge(dut.clk)
    assert int(dut.valid_out.value) == 1, "valid_out must be 1 when output_en=1"
    dut._log.info("PASS: valid_out_gated_by_output_en")

# ─────────────────────────────────────────────
# Test 3 — correct serialization order (row-major)
# ─────────────────────────────────────────────

@cocotb.test()
async def test_serialization_order(dut):
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await do_reset(dut)

    # Fill matrix with unique values: results[i][j] = i*8+j (0..63)
    matrix = np.arange(ARRAY_SIZE * ARRAY_SIZE, dtype=np.int64).reshape(ARRAY_SIZE, ARRAY_SIZE)
    received, done_seen = await collect_outputs(dut, matrix)

    expected = [int(v) for v in matrix.flatten()]
    assert done_seen, "output_done never asserted"
    assert len(received) == ARRAY_SIZE * ARRAY_SIZE, f"Expected 64 bytes, got {len(received)}"
    assert received == expected, f"Order wrong:\ngot:      {received}\nexpected: {expected}"
    dut._log.info("PASS: serialization_order")

# ─────────────────────────────────────────────
# Test 4 — saturation positive: value > 127 → 127
# ─────────────────────────────────────────────

@cocotb.test()
async def test_saturation_positive(dut):
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await do_reset(dut)

    matrix = np.full((ARRAY_SIZE, ARRAY_SIZE), 1048575, dtype=np.int64)  # max 21-bit signed
    received, _ = await collect_outputs(dut, matrix)

    assert all(v == 127 for v in received), f"Positive saturation failed: {received}"
    dut._log.info("PASS: saturation_positive  (1048575 → 127)")

# ─────────────────────────────────────────────
# Test 5 — saturation negative: value < -128 → -128
# ─────────────────────────────────────────────

@cocotb.test()
async def test_saturation_negative(dut):
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await do_reset(dut)

    matrix = np.full((ARRAY_SIZE, ARRAY_SIZE), -1048576, dtype=np.int64)  # min 21-bit signed
    received, _ = await collect_outputs(dut, matrix)

    assert all(v == -128 for v in received), f"Negative saturation failed: {received}"
    dut._log.info("PASS: saturation_negative  (-1048576 → -128)")

# ─────────────────────────────────────────────
# Test 6 — saturation boundary: 127 and -128 pass through unchanged
# ─────────────────────────────────────────────

@cocotb.test()
async def test_saturation_boundary(dut):
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await do_reset(dut)

    matrix = np.zeros((ARRAY_SIZE, ARRAY_SIZE), dtype=np.int64)
    for i in range(ARRAY_SIZE):
        for j in range(ARRAY_SIZE):
            matrix[i][j] = 127 if (i + j) % 2 == 0 else -128

    received, _ = await collect_outputs(dut, matrix)
    expected = [saturate(int(matrix[i][j]))
                for i in range(ARRAY_SIZE) for j in range(ARRAY_SIZE)]
    assert received == expected, f"Boundary saturation failed:\ngot:      {received}\nexpected: {expected}"
    dut._log.info("PASS: saturation_boundary")

# ─────────────────────────────────────────────
# Test 7 — output_done is a single-cycle pulse
# ─────────────────────────────────────────────

@cocotb.test()
async def test_output_done_single_pulse(dut):
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await do_reset(dut)

    matrix = np.ones((ARRAY_SIZE, ARRAY_SIZE), dtype=np.int64)
    dut.results.value   = pack_results(matrix)
    dut.output_en.value = 1
    dut.ready_out.value = 1

    done_count = 0
    for _ in range(ARRAY_SIZE * ARRAY_SIZE + 10):
        await RisingEdge(dut.clk)
        if int(dut.output_done.value) == 1:
            done_count += 1

    dut.output_en.value = 0
    assert done_count == 1, f"output_done should pulse exactly once, got {done_count}"
    dut._log.info("PASS: output_done_single_pulse")

# ─────────────────────────────────────────────
# Test 8 — backpressure: ready_out=0 stalls output
# ─────────────────────────────────────────────

@cocotb.test()
async def test_backpressure(dut):
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await do_reset(dut)

    matrix = np.arange(ARRAY_SIZE * ARRAY_SIZE, dtype=np.int64).reshape(ARRAY_SIZE, ARRAY_SIZE)

    # ready_out=0 for first 5 cycles, then 1
    def ready_fn(cycle):
        return 0 if cycle < 5 else 1

    received, done_seen = await collect_outputs(dut, matrix, ready_fn=ready_fn)
    expected = [int(v) for v in matrix.flatten()]

    assert done_seen, "output_done never asserted"
    assert len(received) == 64, f"Expected 64 bytes, got {len(received)}"
    assert received == expected, f"Backpressure corrupted data:\ngot:      {received}\nexpected: {expected}"
    dut._log.info("PASS: backpressure")

# ─────────────────────────────────────────────
# Test 9 — intermittent backpressure (ready toggles every cycle)
# ─────────────────────────────────────────────

@cocotb.test()
async def test_backpressure_intermittent(dut):
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await do_reset(dut)

    matrix = np.arange(ARRAY_SIZE * ARRAY_SIZE, dtype=np.int64).reshape(ARRAY_SIZE, ARRAY_SIZE)

    def ready_fn(cycle):
        return cycle % 2  # alternates 0,1,0,1,...

    received, done_seen = await collect_outputs(dut, matrix, ready_fn=ready_fn)
    expected = [int(v) for v in matrix.flatten()]

    assert done_seen, "output_done never asserted"
    assert received == expected, f"Intermittent backpressure failed:\ngot:      {received}\nexpected: {expected}"
    dut._log.info("PASS: backpressure_intermittent")

# ─────────────────────────────────────────────
# Test 10 — output_en=0 resets counters (restart from [0][0])
# ─────────────────────────────────────────────

@cocotb.test()
async def test_output_en_reset(dut):
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await do_reset(dut)

    matrix = np.arange(ARRAY_SIZE * ARRAY_SIZE, dtype=np.int64).reshape(ARRAY_SIZE, ARRAY_SIZE)
    dut.results.value   = pack_results(matrix)
    dut.ready_out.value = 1

    # Run 4 cycles then disable
    dut.output_en.value = 1
    for _ in range(4):
        await RisingEdge(dut.clk)

    dut.output_en.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    # Restart — should begin from [0][0] again
    received, done_seen = await collect_outputs(dut, matrix)
    expected = [int(v) for v in matrix.flatten()]

    assert done_seen, "output_done never asserted after restart"
    assert received == expected, f"Restart failed:\ngot:      {received}\nexpected: {expected}"
    dut._log.info("PASS: output_en_reset")

# ─────────────────────────────────────────────
# Test 11 — exactly 64 bytes transferred
# ─────────────────────────────────────────────

@cocotb.test()
async def test_exactly_64_bytes(dut):
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await do_reset(dut)

    matrix = np.ones((ARRAY_SIZE, ARRAY_SIZE), dtype=np.int64) * 42
    received, done_seen = await collect_outputs(dut, matrix)

    assert done_seen, "output_done never asserted"
    assert len(received) == 64, f"Expected exactly 64 bytes, got {len(received)}"
    dut._log.info("PASS: exactly_64_bytes")

# ─────────────────────────────────────────────
# Test 12 — random matrix with mixed saturation
# ─────────────────────────────────────────────

@cocotb.test()
async def test_random_with_saturation(dut):
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    random.seed(99)
    errors = 0

    for trial in range(5):
        await do_reset(dut)

        # Mix: some in range, some saturating
        matrix = np.random.randint(-200000, 200000,
                                   (ARRAY_SIZE, ARRAY_SIZE), dtype=np.int64)
        received, done_seen = await collect_outputs(dut, matrix)
        expected = [saturate(int(matrix[i][j]))
                    for i in range(ARRAY_SIZE) for j in range(ARRAY_SIZE)]

        if not done_seen:
            dut._log.error(f"Trial {trial}: output_done never asserted")
            errors += 1
        elif received != expected:
            dut._log.error(f"Trial {trial} FAIL:\ngot:      {received}\nexpected: {expected}")
            errors += 1
        else:
            dut._log.info(f"  trial {trial} OK")

    assert errors == 0, f"{errors}/5 random trials failed"
    dut._log.info("PASS: random_with_saturation (5 trials)")