"""
cocotb testbench for systolic_array
Team Maxilerator | SSCS Chipathon 2026

Port packing convention (matches systolic_array.sv):
  a_in  [ARRAY_SIZE*DATA_WIDTH-1:0]  — row i at bits [i*8 +: 8]
  b_in  [ARRAY_SIZE*DATA_WIDTH-1:0]  — col j at bits [j*8 +: 8]
  results [ARRAY_SIZE*ARRAY_SIZE*ACCUM_WIDTH-1:0]
        — result[i][j] at bits [(i*ARRAY_SIZE+j)*21 +: 21]

The systolic array is OUTPUT-STATIONARY with a SKEW INPUT pattern.
The feeder drives skewed inputs; here we drive them manually so we
can test the array in isolation against a numpy reference.

Skewed drive pattern for an NxN array computing C = A x B:
  At valid pulse k (k=0..N-1):
    a_in[i] = A[i][k]   (column k of A, row i)
    b_in[j] = B[k][j]   (row k of B, col j)
  After N valid pulses all MACs have accumulated their correct dot product.
  Then N-1 drain pulses flush the pipeline (zeros on inputs, valid=1).
  Total: N + (N-1) = 2N-1 valid pulses needed for a single 8x8 tile.

NOTE: mac_unit registers a_out/b_out on EVERY valid cycle (systolic
pipeline). So MAC[i][j] sees A[i][k] and B[k][j] only when the data
has propagated i hops right and j hops down from the edges.
That means we need to skew the edge inputs:
  At edge pulse k: a_in[i] = A[i][k-i]  (zero-padded outside 0..N-1)
                   b_in[j] = B[k-j][j]  (zero-padded outside 0..N-1)
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
import numpy as np
import random

ARRAY_SIZE  = 8
DATA_WIDTH  = 8
ACCUM_WIDTH = 21

# ─────────────────────────────────────────────
# Port helpers
# ─────────────────────────────────────────────

def pack_a(row_vec):
    """Pack list of N int8 values into a_in flat integer."""
    val = 0
    for i, v in enumerate(row_vec):
        val |= (int(v) & 0xFF) << (i * DATA_WIDTH)
    return val

def pack_b(col_vec):
    """Pack list of N int8 values into b_in flat integer."""
    val = 0
    for j, v in enumerate(col_vec):
        val |= (int(v) & 0xFF) << (j * DATA_WIDTH)
    return val

def read_results(dut):
    """Unpack results port into NxN numpy array of signed ints."""
    raw = int(dut.results.value)
    out = np.zeros((ARRAY_SIZE, ARRAY_SIZE), dtype=np.int64)
    mask = (1 << ACCUM_WIDTH) - 1
    sign_bit = 1 << (ACCUM_WIDTH - 1)
    for i in range(ARRAY_SIZE):
        for j in range(ARRAY_SIZE):
            bits = (raw >> ((i * ARRAY_SIZE + j) * ACCUM_WIDTH)) & mask
            if bits & sign_bit:
                bits -= (1 << ACCUM_WIDTH)
            out[i][j] = bits
    return out

async def do_reset(dut):
    dut.rst_n.value = 0
    dut.valid.value = 0
    dut.clear.value = 0
    dut.a_in.value  = 0
    dut.b_in.value  = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

async def do_clear(dut):
    dut.clear.value = 1
    await RisingEdge(dut.clk)
    dut.clear.value = 0
    await RisingEdge(dut.clk)

# ─────────────────────────────────────────────
# Core driver: feed one NxN tile with skewed inputs
# Returns numpy result matrix
# ─────────────────────────────────────────────

async def compute_tile(dut, A, B):
    N = ARRAY_SIZE
    total_pulses = 3 * N - 2   # 22 for N=8: N data + 2*(N-1) drain

    for pulse in range(total_pulses):
        a_edge = []
        b_edge = []
        for i in range(N):
            k = pulse - i
            a_edge.append(A[i][k] if 0 <= k < N else 0)
        for j in range(N):
            k = pulse - j
            b_edge.append(B[k][j] if 0 <= k < N else 0)

        dut.a_in.value  = pack_a(a_edge)
        dut.b_in.value  = pack_b(b_edge)
        dut.valid.value = 1
        await RisingEdge(dut.clk)

    dut.valid.value = 0
    dut.a_in.value  = 0
    dut.b_in.value  = 0
    await RisingEdge(dut.clk)

    return read_results(dut)

# ─────────────────────────────────────────────
# Test 1 — reset clears all results
# ─────────────────────────────────────────────

@cocotb.test()
async def test_reset(dut):
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await do_reset(dut)
    res = read_results(dut)
    assert np.all(res == 0), f"results not zero after reset:\n{res}"
    dut._log.info("PASS: reset")

# ─────────────────────────────────────────────
# Test 2 — identity matrix: A=I, B=I → C=I
# ─────────────────────────────────────────────

@cocotb.test()
async def test_identity(dut):
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await do_reset(dut)
    N = ARRAY_SIZE
    I = np.eye(N, dtype=np.int64)
    res = await compute_tile(dut, I, I)
    assert np.array_equal(res, I), f"I×I != I:\n{res}"
    dut._log.info("PASS: identity")

# ─────────────────────────────────────────────
# Test 3 — all-ones matrix: A=1, B=1 → C[i][j]=N
# ─────────────────────────────────────────────

@cocotb.test()
async def test_all_ones(dut):
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await do_reset(dut)
    N = ARRAY_SIZE
    A = np.ones((N, N), dtype=np.int64)
    B = np.ones((N, N), dtype=np.int64)
    expected = np.full((N, N), N, dtype=np.int64)
    res = await compute_tile(dut, A, B)
    assert np.array_equal(res, expected), f"all-ones failed:\n{res}\nexpected:\n{expected}"
    dut._log.info(f"PASS: all_ones  (each element = {N})")

# ─────────────────────────────────────────────
# Test 4 — single non-zero element
# ─────────────────────────────────────────────

@cocotb.test()
async def test_single_element(dut):
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await do_reset(dut)
    N = ARRAY_SIZE
    A = np.zeros((N, N), dtype=np.int64)
    B = np.zeros((N, N), dtype=np.int64)
    A[2][3] = 5
    B[3][4] = 7
    expected = np.zeros((N, N), dtype=np.int64)
    expected[2][4] = 35   # only MAC[2][4] fires: A[2][3]*B[3][4]
    res = await compute_tile(dut, A, B)
    assert np.array_equal(res, expected), f"single-element failed:\n{res}\nexpected:\n{expected}"
    dut._log.info("PASS: single_element")

# ─────────────────────────────────────────────
# Test 5 — clear resets all accumulators
# ─────────────────────────────────────────────

@cocotb.test()
async def test_clear(dut):
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await do_reset(dut)
    N = ARRAY_SIZE
    A = np.ones((N, N), dtype=np.int64)
    B = np.ones((N, N), dtype=np.int64)
    await compute_tile(dut, A, B)   # load up accumulators

    await do_clear(dut)
    res = read_results(dut)
    assert np.all(res == 0), f"clear failed, results:\n{res}"
    dut._log.info("PASS: clear")

# ─────────────────────────────────────────────
# Test 7 — signed values: negative inputs
# ─────────────────────────────────────────────

@cocotb.test()
async def test_signed_negative(dut):
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await do_reset(dut)
    N = ARRAY_SIZE
    A = np.full((N, N), -1, dtype=np.int64)
    B = np.full((N, N),  1, dtype=np.int64)
    expected = A @ B   # each element = -N = -8
    res = await compute_tile(dut, A, B)
    assert np.array_equal(res, expected), \
        f"signed negative failed:\ngot:\n{res}\nexpected:\n{expected}"
    dut._log.info(f"PASS: signed_negative  (each element = {expected[0,0]})")

# ─────────────────────────────────────────────
# Test 8 — worst case: -128 × -128, accumulate 8 times = 131072
# ─────────────────────────────────────────────

@cocotb.test()
async def test_worst_case(dut):
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await do_reset(dut)
    N = ARRAY_SIZE
    A = np.full((N, N), -128, dtype=np.int64)
    B = np.full((N, N), -128, dtype=np.int64)
    expected = A @ B   # each = 8 * 16384 = 131072; fits in 21-bit signed (max 1048575)
    res = await compute_tile(dut, A, B)
    assert np.array_equal(res, expected), \
        f"worst_case failed:\ngot:\n{res}\nexpected:\n{expected}"
    dut._log.info(f"PASS: worst_case  (each element = {expected[0,0]})")

# ─────────────────────────────────────────────
# Test 10 — no accumulation when valid=0
# ─────────────────────────────────────────────

@cocotb.test()
async def test_no_accum_without_valid(dut):
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await do_reset(dut)
    N = ARRAY_SIZE

    # Drive inputs for 10 cycles with valid=0
    for _ in range(10):
        dut.a_in.value  = pack_a([127] * N)
        dut.b_in.value  = pack_b([127] * N)
        dut.valid.value = 0
        await RisingEdge(dut.clk)

    await RisingEdge(dut.clk)
    res = read_results(dut)
    assert np.all(res == 0), f"accum changed without valid:\n{res}"
    dut._log.info("PASS: no_accum_without_valid")

# ─────────────────────────────────────────────
# Test 12 — a_out/b_out pipeline flow (data propagates rightward/downward)
# ─────────────────────────────────────────────

@cocotb.test()
async def test_pipeline_flow(dut):
    """
    Drive a single non-zero value on a_in[0] and b_in[0] with valid=1.
    After N valid pulses the value should have propagated across all MACs.
    Verified indirectly via the matmul result.
    """
    cocotb.start_soon(Clock(dut.clk, 40, units="ns").start())
    await do_reset(dut)
    N = ARRAY_SIZE

    # A = row 0 all-3, rest zero; B = col 0 all-2, rest zero
    A = np.zeros((N, N), dtype=np.int64)
    B = np.zeros((N, N), dtype=np.int64)
    A[0, :] = 3
    B[:, 0] = 2

    expected = A @ B   # only column 0 of result is non-zero: C[0][0] = 8*6 = 48
    res = await compute_tile(dut, A, B)
    assert np.array_equal(res, expected), \
        f"pipeline_flow failed:\ngot:\n{res}\nexpected:\n{expected}"
    dut._log.info("PASS: pipeline_flow")