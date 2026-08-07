# tb_systolic_array.py
#
# cocotb testbench for systolic_array.
#
# systolic_array wires an ARRAY_SIZE x ARRAY_SIZE grid of mac_unit PEs: a_in flows
# left to right, b_in flows top to bottom, one hop per cycle. It has no awareness
# of skewing itself -- correct matrix multiply results require the caller to
# pre-skew inputs (row i delayed by i pulses) exactly as feeder does. Since
# mac_unit's own arithmetic is verified separately, this testbench focuses on
# what's unique here: PE-to-PE wiring direction, valid/clear broadcast to every
# PE, the packed input/output bus mapping, and end-to-end matmul correctness
# given a properly pre-skewed feed.
#
# Test cases:
#   1  Reset                    -- results bus all zero after reset
#   2  Clear broadcast          -- clear zeroes every PE simultaneously
#   3  Wavefront trace (A)      -- confirms a_in propagates left-to-right,
#                                  one cycle per hop
#   4  Wavefront trace (B)      -- confirms b_in propagates top-to-bottom,
#                                  one cycle per hop
#   5  Valid gating broadcast   -- valid=0 -> no PE anywhere accumulates
#   6  Results bus packing      -- distinct per-PE values land at the
#                                  correct flat bus offset
#   7  Identity matmul          -- A=I, B=random -> C must equal B exactly
#   8  Random matmul            -- full random NxN matmul vs numpy
#   9  Multiple passes          -- two passes without clear accumulate
#                                  (output-stationary)
#
# Run with: make TOPLEVEL=systolic_array

import cocotb
import numpy as np
from cocotb.clock import Clock
from cocotb.triggers import Timer, RisingEdge

ARRAY_SIZE  = 8
DATA_WIDTH  = 8
ACCUM_WIDTH = 21

DATA_MIN = -(1 << (DATA_WIDTH - 1))
DATA_MAX = (1 << (DATA_WIDTH - 1)) - 1


# =========================================================================
# Setup
# =========================================================================

async def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, 10, "ns").start())

async def reset_dut(dut):
    dut.rst_n.value = 0
    dut.a_in.value = 0
    dut.b_in.value = 0
    dut.valid.value = 0
    dut.clear.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")


# =========================================================================
# Helpers
# =========================================================================

def to_signed(value, width):
    value &= (1 << width) - 1
    if value & (1 << (width - 1)):
        value -= (1 << width)
    return value

def pack_row(values, width):
    packed = 0
    for i, v in enumerate(values):
        packed |= (v & ((1 << width) - 1)) << (i * width)
    return packed

def read_result(dut, r, c):
    raw = int(dut.results.value)
    idx = r * ARRAY_SIZE + c
    slice_val = (raw >> (idx * ACCUM_WIDTH)) & ((1 << ACCUM_WIDTH) - 1)
    return to_signed(slice_val, ACCUM_WIDTH)

def read_all_results(dut):
    return [[read_result(dut, r, c) for c in range(ARRAY_SIZE)] for r in range(ARRAY_SIZE)]

def pe_a_out(dut, r, c):
    return to_signed(int(dut.gen_rows[r].gen_columns[c].pe.a_out.value), DATA_WIDTH)

def pe_b_out(dut, r, c):
    return to_signed(int(dut.gen_rows[r].gen_columns[c].pe.b_out.value), DATA_WIDTH)

async def drive(dut, a_row, b_row, valid, clear=0):
    dut.a_in.value = pack_row(a_row, DATA_WIDTH)
    dut.b_in.value = pack_row(b_row, DATA_WIDTH)
    dut.valid.value = valid
    dut.clear.value = clear
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")

async def run_matmul(dut, A, B, accumulate_only=False):
    """Feeds A, B (ARRAY_SIZE x ARRAY_SIZE) into the array pre-skewed exactly
    as feeder would (row r's k-th element delayed by r pulses), for one full
    pass plus enough drain pulses for the last wavefront to reach the far
    corner. If accumulate_only, does not clear beforehand."""
    N = ARRAY_SIZE
    if not accumulate_only:
        await drive(dut, [0]*N, [0]*N, valid=0, clear=1)

    total_pulses = N + 2 * (N - 1)
    for p in range(total_pulses):
        a_word = [0] * N
        b_word = [0] * N
        for r in range(N):
            k = p - r
            if 0 <= k < N:
                a_word[r] = int(A[r][k])
        for c in range(N):
            k = p - c
            if 0 <= k < N:
                b_word[c] = int(B[k][c])
        await drive(dut, a_word, b_word, valid=1)


# =========================================================================
# Test 1 -- Reset
# =========================================================================

@cocotb.test()
async def test_reset(dut):
    """results bus all zero immediately after reset."""
    await start_clock(dut)
    await reset_dut(dut)

    for r in range(ARRAY_SIZE):
        for c in range(ARRAY_SIZE):
            assert read_result(dut, r, c) == 0, f"PE({r},{c}) not zero after reset"


# =========================================================================
# Test 2 -- Clear Broadcast
# =========================================================================

@cocotb.test()
async def test_clear_resets_all_pes(dut):
    """clear zeroes every PE's result simultaneously."""
    await start_clock(dut)
    await reset_dut(dut)

    await drive(dut, [5]*ARRAY_SIZE, [5]*ARRAY_SIZE, valid=1)
    await drive(dut, [3]*ARRAY_SIZE, [3]*ARRAY_SIZE, valid=1)

    nonzero = sum(1 for r in range(ARRAY_SIZE) for c in range(ARRAY_SIZE) if read_result(dut, r, c) != 0)
    assert nonzero > 0, "expected some PEs to have accumulated before clear"

    await drive(dut, [0]*ARRAY_SIZE, [0]*ARRAY_SIZE, valid=0, clear=1)
    await Timer(1, unit="ns")

    for r in range(ARRAY_SIZE):
        for c in range(ARRAY_SIZE):
            assert read_result(dut, r, c) == 0, f"PE({r},{c}) not cleared"


# =========================================================================
# Test 3 -- Wavefront Trace, A (left -> right)
# =========================================================================

@cocotb.test()
async def test_wavefront_trace_a(dut):
    """A unique value held continuously at row 0's a_in must appear at
    PE(0,c)'s a_out exactly c+1 cycles after it starts, confirming a_in
    propagates strictly left to right, one hop per cycle."""
    await start_clock(dut)
    await reset_dut(dut)

    TOKEN = 37
    a_row = [TOKEN] + [0] * (ARRAY_SIZE - 1)
    b_row = [0] * ARRAY_SIZE

    dut.a_in.value = pack_row(a_row, DATA_WIDTH)
    dut.b_in.value = pack_row(b_row, DATA_WIDTH)
    dut.valid.value = 1
    dut.clear.value = 0

    for cycle in range(1, ARRAY_SIZE + 1):
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        c = cycle - 1
        assert pe_a_out(dut, 0, c) == TOKEN, (
            f"token not at PE(0,{c}).a_out after {cycle} cycles"
        )
        for future_c in range(c + 1, ARRAY_SIZE):
            assert pe_a_out(dut, 0, future_c) != TOKEN, (
                f"token arrived early at PE(0,{future_c}).a_out"
            )


# =========================================================================
# Test 4 -- Wavefront Trace, B (top -> bottom)
# =========================================================================

@cocotb.test()
async def test_wavefront_trace_b(dut):
    """A unique value held continuously at column 0's b_in must appear at
    PE(r,0)'s b_out exactly r+1 cycles after it starts, confirming b_in
    propagates strictly top to bottom, one hop per cycle."""
    await start_clock(dut)
    await reset_dut(dut)

    TOKEN = 41
    a_row = [0] * ARRAY_SIZE
    b_row = [TOKEN] + [0] * (ARRAY_SIZE - 1)

    dut.a_in.value = pack_row(a_row, DATA_WIDTH)
    dut.b_in.value = pack_row(b_row, DATA_WIDTH)
    dut.valid.value = 1
    dut.clear.value = 0

    for cycle in range(1, ARRAY_SIZE + 1):
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        r = cycle - 1
        assert pe_b_out(dut, r, 0) == TOKEN, (
            f"token not at PE({r},0).b_out after {cycle} cycles"
        )
        for future_r in range(r + 1, ARRAY_SIZE):
            assert pe_b_out(dut, future_r, 0) != TOKEN, (
                f"token arrived early at PE({future_r},0).b_out"
            )


# =========================================================================
# Test 5 -- Valid Gating Broadcast
# =========================================================================

@cocotb.test()
async def test_valid_gating_broadcast(dut):
    """valid=0 means no PE anywhere in the grid accumulates -- checked at
    several distinct grid positions, not just one."""
    await start_clock(dut)
    await reset_dut(dut)

    await drive(dut, [4]*ARRAY_SIZE, [4]*ARRAY_SIZE, valid=0)

    check_positions = [(0, 0), (0, ARRAY_SIZE-1), (ARRAY_SIZE-1, 0), (ARRAY_SIZE-1, ARRAY_SIZE-1), (ARRAY_SIZE//2, ARRAY_SIZE//2)]
    for r, c in check_positions:
        assert read_result(dut, r, c) == 0, f"PE({r},{c}) accumulated despite valid=0"


# =========================================================================
# Test 6 -- Results Bus Packing
# =========================================================================

@cocotb.test()
async def test_results_bus_packing(dut):
    """Distinct per-PE values confirm the packed results bus maps each PE
    to the correct flat offset (row-major: index = r*ARRAY_SIZE + c).
    Uses the same proven pre-skewed feed as the matmul tests -- a single
    pulse can't populate the whole grid at once, since each PE only
    forwards a_in/b_in to its neighbour one cycle after it sees them."""
    await start_clock(dut)
    await reset_dut(dut)

    N = ARRAY_SIZE
    # row r constant at (r+1), column c constant at (c+1) -> each PE(r,c)
    # accumulates N inner-product terms of (r+1)*(c+1), giving a distinct,
    # easily-verified value per position: N*(r+1)*(c+1)
    A = np.array([[r + 1] * N for r in range(N)])
    B = np.array([[c + 1 for c in range(N)] for _ in range(N)])

    await run_matmul(dut, A, B)

    for r in range(N):
        for c in range(N):
            expected = N * (r + 1) * (c + 1)
            assert read_result(dut, r, c) == expected, (
                f"PE({r},{c}): expected {expected}, got {read_result(dut, r, c)}"
            )


# =========================================================================
# Test 7 -- Identity Matmul
# =========================================================================

@cocotb.test()
async def test_identity_matmul(dut):
    """A = Identity, B = random -> C must equal B exactly."""
    await start_clock(dut)
    await reset_dut(dut)

    N = ARRAY_SIZE
    A = np.eye(N, dtype=np.int64)
    rng = np.random.default_rng(1)
    B = rng.integers(DATA_MIN, DATA_MAX + 1, size=(N, N))

    await run_matmul(dut, A, B)

    results = np.array(read_all_results(dut))
    expected = A @ B
    assert np.array_equal(results, expected), f"got\n{results}\nexpected\n{expected}"


# =========================================================================
# Test 8 -- Random Matmul
# =========================================================================

@cocotb.test()
async def test_random_matmul(dut):
    """Full random NxN matmul via a properly pre-skewed feed, vs numpy."""
    await start_clock(dut)
    await reset_dut(dut)

    N = ARRAY_SIZE
    rng = np.random.default_rng(7)
    # kept small enough that A@B can't overflow ACCUM_WIDTH for a single pass
    A = rng.integers(-4, 5, size=(N, N))
    B = rng.integers(-4, 5, size=(N, N))

    await run_matmul(dut, A, B)

    results = np.array(read_all_results(dut))
    expected = A.astype(np.int64) @ B.astype(np.int64)
    assert np.array_equal(results, expected), f"got\n{results}\nexpected\n{expected}"


# =========================================================================
# Test 9 -- Multiple Passes Accumulate
# =========================================================================

@cocotb.test()
async def test_multiple_passes_accumulate(dut):
    """Two matmul passes without clear in between -> results = A1@B1 + A2@B2,
    confirming output-stationary accumulation across passes."""
    await start_clock(dut)
    await reset_dut(dut)

    N = ARRAY_SIZE
    rng = np.random.default_rng(3)
    A1 = rng.integers(-3, 4, size=(N, N))
    B1 = rng.integers(-3, 4, size=(N, N))
    A2 = rng.integers(-3, 4, size=(N, N))
    B2 = rng.integers(-3, 4, size=(N, N))

    await run_matmul(dut, A1, B1, accumulate_only=False)
    await run_matmul(dut, A2, B2, accumulate_only=True)

    results = np.array(read_all_results(dut))
    expected = (A1.astype(np.int64) @ B1.astype(np.int64)) + (A2.astype(np.int64) @ B2.astype(np.int64))
    assert np.array_equal(results, expected), f"got\n{results}\nexpected\n{expected}"
