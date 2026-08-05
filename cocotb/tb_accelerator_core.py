# tb_accelerator_core.py
#
# cocotb integration testbench for accelerator_core.sv.
#
# accelerator_core wires feeder, systolic_array, and output_processor
# together with no controller -- feeder self-generates drain_done,
# output_processor self-generates output_done, and each is wired
# directly to the next stage. This testbench treats accelerator_core
# as a black box: it drives the two AXI4-Stream input channels
# (activation, weight) with real tiled matrix data, reads the result
# channel, and checks against a numpy golden model.
#
# Driving/sampling approach: fully manual, single continuous loop --
# words are driven directly (pre-computed per cycle, advanced only
# when acceptance is actually observed that cycle) and every signal
# is sampled PRE-EDGE, every cycle, with no intermediate per-word
# blocking-wait helper functions. This keeps input driving, output
# reading, and timing all governed by one consistent, easily-audited
# loop rather than several independent helpers that each need to
# agree on timing.
#
# Test cases:
#   1  Single pass (N=ARRAY_SIZE, k=1) matrix multiply correctness
#   2  Multi-pass (N=2*ARRAY_SIZE, k=2) accumulation correctness
#   3  Multi-pass (N=4*ARRAY_SIZE, k=4) accumulation correctness
#   4  Saturation -- deliberately large values, verify end-to-end clamp
#   5  Back-to-back runs -- clean reset between two full computations
#   6  Output backpressure -- out_ready toggling during readout
#   7  Identity matrix -- easy manual-verification sanity check
#   8  Input stall -- gaps in a_valid during the send phase
#
# Run all tests:     make TOPLEVEL=accelerator_core MODULE=tb_accelerator_core
# Run a single test: make TOPLEVEL=accelerator_core MODULE=tb_accelerator_core TESTCASE=test_name

import cocotb
import numpy as np
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

CLK_PERIOD = 40  # ns


# =========================================================================
# Setup
# =========================================================================

def dut_params(dut):
    array_size  = int(dut.ARRAY_SIZE.value)
    data_width  = int(dut.DATA_WIDTH.value)
    accum_width = int(dut.ACCUM_WIDTH.value)
    shift_bits  = int(dut.SHIFT_BITS.value)
    sat_max     = dut.SAT_MAX.value.to_signed()
    sat_min     = dut.SAT_MIN.value.to_signed()
    return array_size, data_width, accum_width, shift_bits, sat_max, sat_min

async def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD, unit="ns").start())

async def reset_dut(dut):
    dut.rst_n.value   = 0
    dut.a_valid.value = 0
    dut.a_last.value  = 0
    dut.a_data.value  = 0
    dut.b_valid.value = 0
    dut.b_last.value  = 0
    dut.b_data.value  = 0
    dut.out_ready.value = 1
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")


# =========================================================================
# Golden Model
# =========================================================================

def golden_matmul(A, B, sat_max, sat_min, shift_bits, data_width):
    """A: (M, K), B: (K, N) -- returns the byte pattern (unsigned,
    data_width bits) expected out of out_data for each C[i][j],
    row-major, after shift-then-saturate quantization."""
    C = A.astype(np.int64) @ B.astype(np.int64)
    C_shifted = C >> shift_bits  # numpy >> on signed dtype is arithmetic
    C_clamped = np.clip(C_shifted, sat_min, sat_max)
    mask = (1 << data_width) - 1
    return (C_clamped & mask).astype(np.int64)


# =========================================================================
# Core Driver -- Fully Manual, Single Loop
# =========================================================================

async def run_matrix(dut, A, B, array_size, data_width,
                     stall_positions=None, out_ready_fn=None,
                     max_cycles=100000):
    """Sends A (array_size, K) / B (K, array_size) tiled across K/
    array_size passes, and reads back array_size^2 results, all in
    one continuous, fully-driven loop -- no per-word blocking-wait
    helpers. Returns the list of received bytes, row-major.

    stall_positions: set of within-vector word indices (0..array_size-1)
    where the A lane holds off (stalls) before offering that word.
    out_ready_fn: optional callable(cycle_index) -> 0/1 for out_ready
    during the output phase; defaults to always 1.
    """
    K = A.shape[1]
    n_passes = K // array_size
    assert n_passes * array_size == K
    total_words = K * array_size
    n_results = array_size * array_size
    mask = (1 << data_width) - 1

    def a_word_for(idx):
        if idx >= total_words:
            return None
        vec = idx // array_size
        row = idx % array_size
        return int(A[row, vec]) & mask

    def b_word_for(idx):
        if idx >= total_words:
            return None
        vec = idx // array_size
        row = idx % array_size
        return int(B[vec, row]) & mask

    stall_positions = stall_positions or set()

    a_idx = 0
    b_idx = 0
    a_stall_remaining = 0
    received = []
    out_ready_cyc = 0

    def drive_a():
        nonlocal a_stall_remaining
        pos_in_vec = a_idx % array_size
        if a_stall_remaining > 0:
            dut.a_valid.value = 0
            dut.a_last.value = 0
            return
        val = a_word_for(a_idx)
        if val is None:
            dut.a_valid.value = 0
            dut.a_last.value = 0
        else:
            dut.a_data.value = val
            dut.a_valid.value = 1
            dut.a_last.value = 1 if (a_idx == total_words - 1) else 0

    def drive_b():
        val = b_word_for(b_idx)
        if val is None:
            dut.b_valid.value = 0
            dut.b_last.value = 0
        else:
            dut.b_data.value = val
            dut.b_valid.value = 1
            dut.b_last.value = 1 if (b_idx == total_words - 1) else 0

    # arm the first potential stall (before word index 0's own
    # position, if 0 is a stall position)
    if 0 in stall_positions:
        a_stall_remaining = 10

    if out_ready_fn is not None:
        dut.out_ready.value = out_ready_fn(0)
    else:
        dut.out_ready.value = 1

    drive_a()
    drive_b()
    await Timer(1, unit="ns")

    for cyc in range(max_cycles):
        a_v = int(dut.a_valid.value)
        a_r = int(dut.a_ready.value)
        b_v = int(dut.b_valid.value)
        b_r = int(dut.b_ready.value)
        o_v = int(dut.out_valid.value)
        o_r = int(dut.out_ready.value)
        o_d = int(dut.out_data.value)

        await RisingEdge(dut.clk)

        if a_stall_remaining > 0:
            a_stall_remaining -= 1
        elif a_v and a_r:
            a_idx += 1
            next_pos = a_idx % array_size
            if next_pos in stall_positions and a_idx < total_words:
                a_stall_remaining = 10

        if b_v and b_r:
            b_idx += 1

        if o_v and o_r:
            received.append(o_d)

        drive_a()
        drive_b()
        if out_ready_fn is not None:
            out_ready_cyc += 1
            dut.out_ready.value = out_ready_fn(out_ready_cyc)
        await Timer(1, unit="ns")

        if len(received) == n_results:
            break
    else:
        assert False, f"timeout: only received {len(received)}/{n_results} results"

    return received


# =========================================================================
# Test 1 -- Single Pass Correctness
# =========================================================================

@cocotb.test()
async def test_1_single_pass_correctness(dut):
    """N=ARRAY_SIZE (k=1), small values (no saturation), verify
    against a numpy golden model."""
    await start_clock(dut)
    await reset_dut(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)

    np.random.seed(1)
    A = np.random.randint(-3, 4, (array_size, array_size), dtype=np.int8)
    B = np.random.randint(-3, 4, (array_size, array_size), dtype=np.int8)

    received = await run_matrix(dut, A, B, array_size, data_width)

    expected = golden_matmul(A, B, sat_max, sat_min, shift_bits, data_width).flatten().tolist()
    assert received == expected, f"got {received}\nexpected {expected}"

    dut._log.info(f"PASS test_1: single pass correct (ARRAY_SIZE={array_size})")


# =========================================================================
# Test 2 -- Multi-Pass Accumulation (k=2)
# =========================================================================

@cocotb.test()
async def test_2_multi_pass_k2(dut):
    """N=2*ARRAY_SIZE (k=2), verify accumulation across passes."""
    await start_clock(dut)
    await reset_dut(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)

    np.random.seed(2)
    K = 2 * array_size
    A = np.random.randint(-2, 3, (array_size, K), dtype=np.int8)
    B = np.random.randint(-2, 3, (K, array_size), dtype=np.int8)

    received = await run_matrix(dut, A, B, array_size, data_width)

    expected = golden_matmul(A, B, sat_max, sat_min, shift_bits, data_width).flatten().tolist()
    assert received == expected, f"got {received}\nexpected {expected}"

    dut._log.info("PASS test_2: multi-pass (k=2) accumulation correct")


# =========================================================================
# Test 3 -- Multi-Pass Accumulation (k=4)
# =========================================================================

@cocotb.test()
async def test_3_multi_pass_k4(dut):
    """N=4*ARRAY_SIZE (k=4), larger-scale accumulation confidence."""
    await start_clock(dut)
    await reset_dut(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)

    np.random.seed(3)
    K = 4 * array_size
    A = np.random.randint(-1, 2, (array_size, K), dtype=np.int8)
    B = np.random.randint(-1, 2, (K, array_size), dtype=np.int8)

    received = await run_matrix(dut, A, B, array_size, data_width)

    expected = golden_matmul(A, B, sat_max, sat_min, shift_bits, data_width).flatten().tolist()
    assert received == expected, f"got {received}\nexpected {expected}"

    dut._log.info("PASS test_3: multi-pass (k=4) accumulation correct")


# =========================================================================
# Test 4 -- Saturation
# =========================================================================

@cocotb.test()
async def test_4_saturation(dut):
    """Deliberately large values that saturate -- verify end-to-end
    clamping through systolic_array and output_processor together."""
    await start_clock(dut)
    await reset_dut(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)

    A = np.full((array_size, array_size), 127, dtype=np.int8)
    B = np.full((array_size, array_size), 127, dtype=np.int8)

    received = await run_matrix(dut, A, B, array_size, data_width)

    expected = golden_matmul(A, B, sat_max, sat_min, shift_bits, data_width).flatten().tolist()
    assert received == expected, f"got {received}\nexpected {expected}"
    assert all(v == (sat_max & ((1 << data_width) - 1)) for v in received), \
        "expected uniform saturation to SAT_MAX"

    dut._log.info("PASS test_4: saturation correctly propagated end-to-end")


# =========================================================================
# Test 5 -- Back-to-Back Runs
# =========================================================================

@cocotb.test()
async def test_5_back_to_back(dut):
    """Two full computations in sequence -- verify clean reset (clear
    propagating correctly from output_processor to feeder and
    systolic_array) between runs."""
    await start_clock(dut)
    await reset_dut(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)

    for run in range(2):
        np.random.seed(10 + run)
        A = np.random.randint(-3, 4, (array_size, array_size), dtype=np.int8)
        B = np.random.randint(-3, 4, (array_size, array_size), dtype=np.int8)

        received = await run_matrix(dut, A, B, array_size, data_width)

        expected = golden_matmul(A, B, sat_max, sat_min, shift_bits, data_width).flatten().tolist()
        assert received == expected, f"run {run}: got {received}\nexpected {expected}"

    dut._log.info("PASS test_5: two back-to-back runs both correct")


# =========================================================================
# Test 6 -- Output Backpressure
# =========================================================================

@cocotb.test()
async def test_6_output_backpressure(dut):
    """out_ready toggles on and off during readout -- verify results
    are still received correctly."""
    await start_clock(dut)
    await reset_dut(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)

    np.random.seed(6)
    A = np.random.randint(-3, 4, (array_size, array_size), dtype=np.int8)
    B = np.random.randint(-3, 4, (array_size, array_size), dtype=np.int8)

    received = await run_matrix(dut, A, B, array_size, data_width,
                                out_ready_fn=lambda cyc: 1 if (cyc % 3 != 0) else 0)

    expected = golden_matmul(A, B, sat_max, sat_min, shift_bits, data_width).flatten().tolist()
    assert received == expected, f"got {received}\nexpected {expected}"

    dut._log.info("PASS test_6: output backpressure handled correctly")


# =========================================================================
# Test 7 -- Identity Matrix
# =========================================================================

@cocotb.test()
async def test_7_identity_matrix(dut):
    """A = identity -- C should equal B exactly (easy manual check)."""
    await start_clock(dut)
    await reset_dut(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)

    A = np.eye(array_size, dtype=np.int8)
    np.random.seed(7)
    B = np.random.randint(-5, 6, (array_size, array_size), dtype=np.int8)

    received = await run_matrix(dut, A, B, array_size, data_width)

    expected = golden_matmul(A, B, sat_max, sat_min, shift_bits, data_width).flatten().tolist()
    assert received == expected, f"got {received}\nexpected {expected}"

    dut._log.info("PASS test_7: identity matrix correct (C == B)")


# =========================================================================
# Test 8 -- Input Stall
# =========================================================================

@cocotb.test()
async def test_8_input_stall(dut):
    """Gaps in a_valid during the send phase (host stalling) --
    verify feeder's stall handling doesn't break end-to-end
    correctness."""
    await start_clock(dut)
    await reset_dut(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)

    np.random.seed(8)
    A = np.random.randint(-3, 4, (array_size, array_size), dtype=np.int8)
    B = np.random.randint(-3, 4, (array_size, array_size), dtype=np.int8)

    received = await run_matrix(dut, A, B, array_size, data_width,
                                stall_positions={2, 5})

    expected = golden_matmul(A, B, sat_max, sat_min, shift_bits, data_width).flatten().tolist()
    assert received == expected, f"got {received}\nexpected {expected}"

    dut._log.info("PASS test_8: input stall handled correctly end-to-end")
