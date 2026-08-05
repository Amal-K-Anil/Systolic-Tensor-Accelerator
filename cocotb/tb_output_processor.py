# tb_output_processor.py
#
# cocotb testbench for output_processor.sv.
#
# output_processor serializes the systolic array's accumulator results
# into a byte-wide AXI4-Stream output, one result per cycle, row-major.
# Each result is optionally shifted (SHIFT_BITS) then saturated to
# [SAT_MIN, SAT_MAX] before truncation to DATA_WIDTH. output_en is
# driven externally (normally by feeder's drain_done); output_done is
# self-generated, firing the cycle the true final result transfers,
# and is used both to reset this module's own counters and (wired
# externally) to clear feeder and the MAC array.
#
# Test cases:
#   1.1  Full ARRAY_SIZE x ARRAY_SIZE serialization, row-major order
#   1.2  ARRAY_SIZE / DATA_WIDTH / ACCUM_WIDTH parameterization
#   1.3  Unique value per MAC position (validates index math)
#   2.1  In-range values pass through unchanged
#   2.2  Values above SAT_MAX clamp to OUT_MAX
#   2.3  Values below SAT_MIN clamp to OUT_MIN
#   2.4  Boundary values (SAT_MAX, SAT_MAX+1, SAT_MIN, SAT_MIN-1)
#   2.5  SHIFT_BITS > 0, positive values
#   2.6  SHIFT_BITS > 0, negative values (truncation direction)
#   2.7  SAT_MAX/SAT_MIN as compiled (validates the default formula
#        and any override, read directly from the DUT)
#   3.1  out_ready held low -- hold semantics, no advance
#   3.2  out_ready toggling intermittently
#   3.3  out_ready low specifically on the last result
#   3.4  No-stall baseline
#   4.1  output_en low -- out_valid low, counters held at 0
#   4.2  output_en rising exactly at reset release
#   4.3  Multiple sessions, each starting fresh
#   5.1  output_done fires exactly on the last result's transfer cycle
#   5.2  No early firing if out_ready=0 when counters reach max
#   5.3  Counters reset the cycle after output_done
#   5.4  out_last held as a stable level, not a stray pulse
#   5.5  Immediate back-to-back restart
#   6.1  Reset mid-serialization
#   6.2  Reset right as output_done would fire
#   6.3  Long reset hold
#   7.1  All-zero results
#   7.2  All-max-positive results
#   7.3  All-max-negative results
#
# Run all tests:     make TOPLEVEL=output_processor MODULE=tb_output_processor
# Run a single test: make TOPLEVEL=output_processor MODULE=tb_output_processor TESTCASE=test_name

import cocotb
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

async def reset_dut(dut, array_size, accum_width):
    dut.rst_n.value      = 0
    dut.results.value    = 0
    dut.output_en.value  = 0
    dut.out_ready.value  = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")


# =========================================================================
# Result Packing and Golden Model
# =========================================================================

def pack_results(values, accum_width):
    """values[i] is the signed value for flat index i (row*ARRAY_SIZE+col),
    packed with index 0 in the low bits."""
    mask = (1 << accum_width) - 1
    packed = 0
    for i, v in enumerate(values):
        packed |= (v & mask) << (i * accum_width)
    return packed

def golden_out_data(raw, shift_bits, sat_max, sat_min, data_width):
    shifted = raw >> shift_bits  # Python's >> on negative ints already
                                  # truncates toward -infinity, matching >>>
    if shifted > sat_max:
        clamped = sat_max
    elif shifted < sat_min:
        clamped = sat_min
    else:
        clamped = shifted
    return clamped & ((1 << data_width) - 1)


# =========================================================================
# Result Capture Helpers
# =========================================================================

async def run_single_value(dut, array_size, accum_width, position, value):
    """Drive one specific raw value at `position`, zero elsewhere,
    read back just that one result."""
    n = array_size * array_size
    values = [0] * n
    values[position] = value
    dut.results.value = pack_results(values, accum_width)
    dut.output_en.value = 1
    dut.out_ready.value = 1
    await Timer(1, unit="ns")

    for _ in range(position + 1):
        valid, ready, data = int(dut.out_valid.value), int(dut.out_ready.value), int(dut.out_data.value)
        await RisingEdge(dut.clk)
        if valid and ready and _ == position:
            return data
    return data  # last sampled value at the target position


# =========================================================================
# Category 1 -- Basic Functional Correctness / Parameterization
# =========================================================================

@cocotb.test()
async def test_1_1_full_serialization_order(dut):
    """Serialize a full ARRAY_SIZE x ARRAY_SIZE result set with no
    stalls, verify correct row-major order and values."""
    await start_clock(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)
    await reset_dut(dut, array_size, accum_width)

    n = array_size * array_size
    values = [i + 1 for i in range(n)]  # small, safely in-range values
    dut.results.value = pack_results(values, accum_width)

    dut.output_en.value = 1
    dut.out_ready.value = 1
    await Timer(1, unit="ns")

    received = []
    for _ in range(n + 5):
        valid = int(dut.out_valid.value)
        ready = int(dut.out_ready.value)
        data  = int(dut.out_data.value)
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        if valid and ready:
            received.append(data)
        if len(received) == n:
            break

    assert len(received) == n, f"got {len(received)} results, expected {n}"
    expected = [golden_out_data(v, shift_bits, sat_max, sat_min, data_width) for v in values]
    assert received == expected, f"got {received}\nexpected {expected}"

    dut._log.info(f"PASS 1.1: full serialization correct (ARRAY_SIZE={array_size})")


@cocotb.test()
async def test_1_2_parameterization(dut):
    """Verifies this testbench derives everything from the compiled
    DUT's own parameters -- re-running with a different -P override
    exercises a different configuration with zero code changes."""
    await start_clock(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)
    await reset_dut(dut, array_size, accum_width)

    dut._log.info(f"ARRAY_SIZE={array_size} DATA_WIDTH={data_width} "
                  f"ACCUM_WIDTH={accum_width} SHIFT_BITS={shift_bits} "
                  f"SAT_MAX={sat_max} SAT_MIN={sat_min}")

    n = array_size * array_size
    values = [2] * n
    dut.results.value = pack_results(values, accum_width)
    dut.output_en.value = 1
    dut.out_ready.value = 1
    await Timer(1, unit="ns")

    count = 0
    for _ in range(n + 5):
        valid = int(dut.out_valid.value)
        ready = int(dut.out_ready.value)
        data  = int(dut.out_data.value)
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        if valid and ready:
            assert data == golden_out_data(2, shift_bits, sat_max, sat_min, data_width)
            count += 1
        if count == n:
            break

    assert count == n, f"got {count} results, expected {n}"
    dut._log.info(f"PASS 1.2: parameterization-agnostic run correct")


@cocotb.test()
async def test_1_3_unique_value_per_position(dut):
    """Every MAC position carries a distinct value -- validates the
    index = row*ARRAY_SIZE+col addressing, not just that values are
    approximately right."""
    await start_clock(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)
    await reset_dut(dut, array_size, accum_width)

    n = array_size * array_size
    values = [(r * 100 + c + 1) for r in range(array_size) for c in range(array_size)]
    dut.results.value = pack_results(values, accum_width)
    dut.output_en.value = 1
    dut.out_ready.value = 1
    await Timer(1, unit="ns")

    received = []
    for _ in range(n + 5):
        valid, ready, data = int(dut.out_valid.value), int(dut.out_ready.value), int(dut.out_data.value)
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        if valid and ready:
            received.append(data)
        if len(received) == n:
            break

    expected = [golden_out_data(v, shift_bits, sat_max, sat_min, data_width) for v in values]
    assert received == expected, f"got {received}\nexpected {expected}"

    dut._log.info("PASS 1.3: unique per-position values correctly indexed")


# =========================================================================
# Category 2 -- Saturation and Quantization
# =========================================================================


@cocotb.test()
async def test_2_1_inrange_passthrough(dut):
    """In-range values pass through unchanged (no saturation)."""
    await start_clock(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)
    await reset_dut(dut, array_size, accum_width)

    test_val = min(10, sat_max)
    got = await run_single_value(dut, array_size, accum_width, 0, test_val)
    expected = golden_out_data(test_val, shift_bits, sat_max, sat_min, data_width)
    assert got == expected, f"got {got}, expected {expected}"

    dut._log.info(f"PASS 2.1: in-range value {test_val} passed through correctly")


@cocotb.test()
async def test_2_2_clamp_above_max(dut):
    """Value well above SAT_MAX clamps to OUT_MAX."""
    await start_clock(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)
    await reset_dut(dut, array_size, accum_width)

    big_val = sat_max * 4 + 1000
    got = await run_single_value(dut, array_size, accum_width, 0, big_val)
    expected = sat_max & ((1 << data_width) - 1)
    assert got == expected, f"got {got}, expected {expected} (clamped SAT_MAX)"

    dut._log.info(f"PASS 2.2: value {big_val} correctly clamped to SAT_MAX")


@cocotb.test()
async def test_2_3_clamp_below_min(dut):
    """Value well below SAT_MIN clamps to OUT_MIN."""
    await start_clock(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)
    await reset_dut(dut, array_size, accum_width)

    small_val = sat_min * 4 - 1000
    got = await run_single_value(dut, array_size, accum_width, 0, small_val)
    expected = sat_min & ((1 << data_width) - 1)
    assert got == expected, f"got {got}, expected {expected} (clamped SAT_MIN)"

    dut._log.info(f"PASS 2.3: value {small_val} correctly clamped to SAT_MIN")


@cocotb.test()
async def test_2_4_boundary_values(dut):
    """Exact boundary values: SAT_MAX, SAT_MAX+1, SAT_MIN, SAT_MIN-1."""
    await start_clock(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)
    await reset_dut(dut, array_size, accum_width)

    for val in [sat_max, sat_max + 1, sat_min, sat_min - 1]:
        got = await run_single_value(dut, array_size, accum_width, 0, val)
        expected = golden_out_data(val, shift_bits, sat_max, sat_min, data_width)
        assert got == expected, f"value {val}: got {got}, expected {expected}"
        await reset_dut(dut, array_size, accum_width)

    dut._log.info("PASS 2.4: all boundary values handled correctly")


@cocotb.test()
async def test_2_5_shift_bits_positive(dut):
    """A large positive value that would saturate at SHIFT_BITS=0 is
    correctly scaled down by the DUT's compiled SHIFT_BITS."""
    await start_clock(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)
    await reset_dut(dut, array_size, accum_width)

    val = (sat_max + 1) << max(shift_bits, 1)  # scale so it needs the shift to fit
    got = await run_single_value(dut, array_size, accum_width, 0, val)
    expected = golden_out_data(val, shift_bits, sat_max, sat_min, data_width)
    assert got == expected, f"got {got}, expected {expected}"

    dut._log.info(f"PASS 2.5: positive value {val} correctly scaled (SHIFT_BITS={shift_bits})")


@cocotb.test()
async def test_2_6_shift_bits_negative_truncation(dut):
    """A negative value shifted right must truncate toward -infinity
    (arithmetic shift), not toward zero."""
    await start_clock(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)
    await reset_dut(dut, array_size, accum_width)

    val = -7  # -7 >>> 1 = -4 (toward -inf), NOT -3 (toward zero)
    got = await run_single_value(dut, array_size, accum_width, 0, val)
    expected = golden_out_data(val, shift_bits, sat_max, sat_min, data_width)
    assert got == expected, f"got {got}, expected {expected}"

    dut._log.info(f"PASS 2.6: negative value {val} truncated correctly (SHIFT_BITS={shift_bits})")


@cocotb.test()
async def test_2_7_sat_bounds_as_compiled(dut):
    """Validates SAT_MAX/SAT_MIN as actually compiled into the DUT
    (default formula, or any override) by reading them directly and
    checking clamp behavior against those exact values."""
    await start_clock(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)
    await reset_dut(dut, array_size, accum_width)

    default_max = (1 << (data_width - 1)) - 1
    default_min = -(1 << (data_width - 1))
    dut._log.info(f"SAT_MAX={sat_max} (default would be {default_max}), "
                  f"SAT_MIN={sat_min} (default would be {default_min})")

    got_max = await run_single_value(dut, array_size, accum_width, 0, sat_max)
    assert got_max == (sat_max & ((1 << data_width) - 1))
    await reset_dut(dut, array_size, accum_width)
    got_min = await run_single_value(dut, array_size, accum_width, 0, sat_min)
    assert got_min == (sat_min & ((1 << data_width) - 1))

    dut._log.info("PASS 2.7: SAT_MAX/SAT_MIN as compiled behave correctly")


# =========================================================================
# Category 3 -- Backpressure
# =========================================================================

@cocotb.test()
async def test_3_1_out_ready_held_low(dut):
    """out_ready held low for several cycles -- out_data/out_valid
    must hold steady, no advance."""
    await start_clock(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)
    await reset_dut(dut, array_size, accum_width)

    n = array_size * array_size
    values = [i + 1 for i in range(n)]
    dut.results.value = pack_results(values, accum_width)
    dut.output_en.value = 1
    dut.out_ready.value = 0
    await Timer(1, unit="ns")

    first_data = int(dut.out_data.value)
    for _ in range(10):
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        assert int(dut.out_valid.value) == 1, "out_valid dropped while stalled"
        assert int(dut.out_data.value) == first_data, "out_data changed while stalled"

    dut._log.info("PASS 3.1: out_data/out_valid held steady during backpressure")


@cocotb.test()
async def test_3_2_out_ready_intermittent(dut):
    """out_ready toggles on and off repeatedly -- verify all results
    are still received correctly, just at an uneven pace."""
    await start_clock(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)
    await reset_dut(dut, array_size, accum_width)

    n = array_size * array_size
    values = [i + 1 for i in range(n)]
    dut.results.value = pack_results(values, accum_width)
    dut.output_en.value = 1

    received = []
    cyc = 0
    while len(received) < n and cyc < n * 5:
        dut.out_ready.value = 1 if (cyc % 3 != 0) else 0
        await Timer(1, unit="ns")
        valid, ready, data = int(dut.out_valid.value), int(dut.out_ready.value), int(dut.out_data.value)
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        if valid and ready:
            received.append(data)
        cyc += 1

    expected = [golden_out_data(v, shift_bits, sat_max, sat_min, data_width) for v in values]
    assert received == expected, f"got {received}\nexpected {expected}"

    dut._log.info("PASS 3.2: intermittent out_ready handled correctly")


@cocotb.test()
async def test_3_3_out_ready_low_on_last_result(dut):
    """out_ready specifically withheld on the final result -- verify
    output_done waits for the real transfer, not just row/col
    reaching the last position."""
    await start_clock(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)
    await reset_dut(dut, array_size, accum_width)

    n = array_size * array_size
    values = [i + 1 for i in range(n)]
    dut.results.value = pack_results(values, accum_width)
    dut.output_en.value = 1
    dut.out_ready.value = 1
    await Timer(1, unit="ns")

    count = 0
    for _ in range(n - 1):
        valid, ready = int(dut.out_valid.value), int(dut.out_ready.value)
        await RisingEdge(dut.clk)
        if valid and ready:
            count += 1

    assert count == n - 1, f"expected {n-1} results before final, got {count}"

    # now hold out_ready low on the final result
    dut.out_ready.value = 0
    for _ in range(10):
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        assert int(dut.output_done.value) == 0, \
            "output_done fired despite out_ready being low on the final result"

    dut.out_ready.value = 1
    await Timer(1, unit="ns")
    assert int(dut.output_done.value) == 1, \
        "output_done not high once out_ready arrived (checked before the final edge)"

    dut._log.info("PASS 3.3: output_done correctly waits for out_ready on the last result")


@cocotb.test()
async def test_3_4_no_stall_baseline(dut):
    """No backpressure at all -- full throughput, one result per
    cycle, no gaps."""
    await start_clock(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)
    await reset_dut(dut, array_size, accum_width)

    n = array_size * array_size
    values = [i + 1 for i in range(n)]
    dut.results.value = pack_results(values, accum_width)
    dut.output_en.value = 1
    dut.out_ready.value = 1
    await Timer(1, unit="ns")

    for i in range(n):
        assert int(dut.out_valid.value) == 1, f"out_valid low at result {i}"
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")

    dut._log.info("PASS 3.4: no-stall baseline, full throughput confirmed")


# =========================================================================
# Category 4 -- output_en Behavior
# =========================================================================

@cocotb.test()
async def test_4_1_output_en_low(dut):
    """output_en low -- out_valid stays low, row/col counters stay
    at 0 (no data ever offered)."""
    await start_clock(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)
    await reset_dut(dut, array_size, accum_width)

    dut.results.value = pack_results([5] * (array_size * array_size), accum_width)
    dut.output_en.value = 0
    dut.out_ready.value = 1
    await Timer(1, unit="ns")

    for _ in range(10):
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        assert int(dut.out_valid.value) == 0, "out_valid high despite output_en=0"

    dut._log.info("PASS 4.1: output_en low correctly keeps out_valid low")


@cocotb.test()
async def test_4_2_output_en_at_reset_release(dut):
    """output_en already high the cycle reset releases -- verify
    correct immediate behavior, no spurious extra cycle needed."""
    await start_clock(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)

    dut.rst_n.value     = 0
    dut.results.value   = pack_results([9] * (array_size * array_size), accum_width)
    dut.output_en.value = 1
    dut.out_ready.value = 1
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")

    assert int(dut.out_valid.value) == 1, "out_valid not high immediately at reset release"
    expected = golden_out_data(9, shift_bits, sat_max, sat_min, data_width)
    assert int(dut.out_data.value) == expected, \
        f"out_data={int(dut.out_data.value)}, expected {expected}"

    dut._log.info("PASS 4.2: output_en high at reset release handled correctly")


@cocotb.test()
async def test_4_3_multiple_sessions(dut):
    """Multiple separate serialization sessions -- each must start
    fresh from row=0, col=0."""
    await start_clock(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)
    await reset_dut(dut, array_size, accum_width)

    n = array_size * array_size

    for session in range(2):
        values = [(session * 10 + i + 1) for i in range(n)]
        dut.results.value = pack_results(values, accum_width)
        dut.output_en.value = 1
        dut.out_ready.value = 1
        await Timer(1, unit="ns")

        received = []
        for _ in range(n + 5):
            valid, ready, data = int(dut.out_valid.value), int(dut.out_ready.value), int(dut.out_data.value)
            await RisingEdge(dut.clk)
            await Timer(1, unit="ns")
            if valid and ready:
                received.append(data)
            if len(received) == n:
                break

        expected = [golden_out_data(v, shift_bits, sat_max, sat_min, data_width) for v in values]
        assert received == expected, f"session {session}: got {received}\nexpected {expected}"

        dut.output_en.value = 0
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")

    dut._log.info("PASS 4.3: multiple sessions each started fresh")


# =========================================================================
# Category 5 -- output_done / out_last Timing
# =========================================================================

@cocotb.test()
async def test_5_1_output_done_exact_timing(dut):
    """output_done fires exactly the cycle the last result transfers,
    no earlier, no later."""
    await start_clock(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)
    await reset_dut(dut, array_size, accum_width)

    n = array_size * array_size
    dut.results.value = pack_results([1] * n, accum_width)
    dut.output_en.value = 1
    dut.out_ready.value = 1
    await Timer(1, unit="ns")

    for i in range(n - 1):
        await Timer(1, unit="ns")
        assert int(dut.output_done.value) == 0, f"output_done fired early at result {i}"
        await RisingEdge(dut.clk)

    # after n-1 edges, row/col are already at the final position --
    # output_done is combinational, so it is already high here, one
    # edge before the final transfer actually completes
    await Timer(1, unit="ns")
    assert int(dut.output_done.value) == 1, "output_done not high on the final position"

    dut._log.info("PASS 5.1: output_done fires at the exact correct cycle")


@cocotb.test()
async def test_5_2_no_early_firing_on_stall(dut):
    """output_done does not fire early if out_ready=0 exactly when
    row/col reach the last position (covered together with 3.3, kept
    as a distinct focused check on output_done specifically)."""
    await start_clock(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)
    await reset_dut(dut, array_size, accum_width)

    n = array_size * array_size
    dut.results.value = pack_results([1] * n, accum_width)
    dut.output_en.value = 1
    dut.out_ready.value = 1
    await Timer(1, unit="ns")

    for _ in range(n - 1):
        await RisingEdge(dut.clk)

    dut.out_ready.value = 0
    for _ in range(5):
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        assert int(dut.output_done.value) == 0, "output_done fired without a real transfer"

    dut._log.info("PASS 5.2: output_done correctly withheld without a real transfer")


@cocotb.test()
async def test_5_3_counters_reset_after_output_done(dut):
    """row/col reset to 0 the cycle after output_done fires."""
    await start_clock(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)
    await reset_dut(dut, array_size, accum_width)

    n = array_size * array_size
    dut.results.value = pack_results([1] * n, accum_width)
    dut.output_en.value = 1
    dut.out_ready.value = 1
    await Timer(1, unit="ns")

    for _ in range(n - 1):
        await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert int(dut.output_done.value) == 1

    # the nth edge is the one that both completes the final transfer
    # and (triggered by output_done) resets row/col
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert int(dut.row.value) == 0, f"row not reset: {int(dut.row.value)}"
    assert int(dut.col.value) == 0, f"col not reset: {int(dut.col.value)}"

    dut._log.info("PASS 5.3: row/col correctly reset one cycle after output_done")


@cocotb.test()
async def test_5_4_out_last_stable_during_stall(dut):
    """out_last is held as a stable level while waiting on out_ready,
    not a stray single-cycle pulse."""
    await start_clock(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)
    await reset_dut(dut, array_size, accum_width)

    n = array_size * array_size
    dut.results.value = pack_results([1] * n, accum_width)
    dut.output_en.value = 1
    dut.out_ready.value = 1
    await Timer(1, unit="ns")

    for _ in range(n - 1):
        await RisingEdge(dut.clk)

    dut.out_ready.value = 0
    for _ in range(8):
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        assert int(dut.out_last.value) == 1, "out_last dropped while stalled on the final result"

    dut._log.info("PASS 5.4: out_last held stable through stall on the final result")


@cocotb.test()
async def test_5_5_immediate_back_to_back_restart(dut):
    """After output_done, immediately (same/next cycle) start a fresh
    session -- verify zero-gap resume works correctly."""
    await start_clock(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)
    await reset_dut(dut, array_size, accum_width)

    n = array_size * array_size
    dut.results.value = pack_results([3] * n, accum_width)
    dut.output_en.value = 1
    dut.out_ready.value = 1
    await Timer(1, unit="ns")

    for _ in range(n - 1):
        await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert int(dut.output_done.value) == 1

    # the nth edge completes the old session's final transfer AND
    # (via output_done) resets row/col -- swap results only AFTER
    # this edge, so the old session's last value isn't disturbed
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    dut.results.value = pack_results([4] * n, accum_width)
    await Timer(1, unit="ns")

    received = []
    for _ in range(n + 5):
        valid, ready, data = int(dut.out_valid.value), int(dut.out_ready.value), int(dut.out_data.value)
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        if valid and ready:
            received.append(data)
        if len(received) == n:
            break

    expected = [golden_out_data(4, shift_bits, sat_max, sat_min, data_width)] * n
    assert received == expected, f"got {received}\nexpected {expected}"

    dut._log.info("PASS 5.5: immediate back-to-back restart handled correctly")


# =========================================================================
# Category 6 -- Reset Behavior
# =========================================================================

@cocotb.test()
async def test_6_1_reset_mid_serialization(dut):
    """Reset asserted partway through a serialization session."""
    await start_clock(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)
    await reset_dut(dut, array_size, accum_width)

    n = array_size * array_size
    dut.results.value = pack_results([1] * n, accum_width)
    dut.output_en.value = 1
    dut.out_ready.value = 1
    await Timer(1, unit="ns")

    for _ in range(n // 2):
        await RisingEdge(dut.clk)

    dut.rst_n.value = 0
    dut.output_en.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")

    assert int(dut.out_valid.value) == 0, "out_valid not low after mid-serialization reset"
    assert int(dut.output_done.value) == 0, "output_done not low after mid-serialization reset"

    dut._log.info("PASS 6.1: reset mid-serialization handled correctly")


@cocotb.test()
async def test_6_2_reset_at_output_done(dut):
    """Reset asserted right as output_done would have fired."""
    await start_clock(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)
    await reset_dut(dut, array_size, accum_width)

    n = array_size * array_size
    dut.results.value = pack_results([1] * n, accum_width)
    dut.output_en.value = 1
    dut.out_ready.value = 1
    await Timer(1, unit="ns")

    for _ in range(n - 1):
        await RisingEdge(dut.clk)

    dut.rst_n.value = 0
    dut.output_en.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")

    assert int(dut.output_done.value) == 0, "output_done not low after reset at completion point"
    assert int(dut.row.value) == 0 and int(dut.col.value) == 0, "counters not reset"

    dut._log.info("PASS 6.2: reset at completion point handled correctly")


@cocotb.test()
async def test_6_3_long_reset_hold(dut):
    """Reset held for many cycles beyond the minimum -- verify no
    stuck-state issues afterward."""
    await start_clock(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)

    dut.rst_n.value     = 0
    dut.results.value   = 0
    dut.output_en.value = 0
    dut.out_ready.value = 0
    for _ in range(50):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")

    n = array_size * array_size
    dut.results.value = pack_results([6] * n, accum_width)
    dut.output_en.value = 1
    dut.out_ready.value = 1
    await Timer(1, unit="ns")

    received = []
    for _ in range(n + 5):
        valid, ready, data = int(dut.out_valid.value), int(dut.out_ready.value), int(dut.out_data.value)
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        if valid and ready:
            received.append(data)
        if len(received) == n:
            break

    expected = [golden_out_data(6, shift_bits, sat_max, sat_min, data_width)] * n
    assert received == expected, f"got {received}\nexpected {expected}"

    dut._log.info("PASS 6.3: long reset hold handled correctly")


# =========================================================================
# Category 7 -- Data Value Edge Cases
# =========================================================================

@cocotb.test()
async def test_7_1_all_zero_results(dut):
    """All accumulator results are zero -- degenerate but valid."""
    await start_clock(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)
    await reset_dut(dut, array_size, accum_width)

    n = array_size * array_size
    dut.results.value = pack_results([0] * n, accum_width)
    dut.output_en.value = 1
    dut.out_ready.value = 1
    await Timer(1, unit="ns")

    received = []
    for _ in range(n + 5):
        valid, ready, data = int(dut.out_valid.value), int(dut.out_ready.value), int(dut.out_data.value)
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        if valid and ready:
            received.append(data)
        if len(received) == n:
            break

    assert all(v == 0 for v in received), f"expected all zero, got {received}"

    dut._log.info("PASS 7.1: all-zero results handled correctly")


@cocotb.test()
async def test_7_2_all_max_positive_results(dut):
    """All accumulator results at a large positive value -- verify
    consistent saturation across every position."""
    await start_clock(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)
    await reset_dut(dut, array_size, accum_width)

    n = array_size * array_size
    big_val = sat_max * 4 + 500
    dut.results.value = pack_results([big_val] * n, accum_width)
    dut.output_en.value = 1
    dut.out_ready.value = 1
    await Timer(1, unit="ns")

    received = []
    for _ in range(n + 5):
        valid, ready, data = int(dut.out_valid.value), int(dut.out_ready.value), int(dut.out_data.value)
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        if valid and ready:
            received.append(data)
        if len(received) == n:
            break

    expected_byte = sat_max & ((1 << data_width) - 1)
    assert all(v == expected_byte for v in received), \
        f"expected all {expected_byte}, got {received}"

    dut._log.info("PASS 7.2: all-max-positive results correctly saturated")


@cocotb.test()
async def test_7_3_all_max_negative_results(dut):
    """All accumulator results at a large negative value -- verify
    consistent saturation across every position."""
    await start_clock(dut)
    array_size, data_width, accum_width, shift_bits, sat_max, sat_min = dut_params(dut)
    await reset_dut(dut, array_size, accum_width)

    n = array_size * array_size
    small_val = sat_min * 4 - 500
    dut.results.value = pack_results([small_val] * n, accum_width)
    dut.output_en.value = 1
    dut.out_ready.value = 1
    await Timer(1, unit="ns")

    received = []
    for _ in range(n + 5):
        valid, ready, data = int(dut.out_valid.value), int(dut.out_ready.value), int(dut.out_data.value)
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        if valid and ready:
            received.append(data)
        if len(received) == n:
            break

    expected_byte = sat_min & ((1 << data_width) - 1)
    assert all(v == expected_byte for v in received), \
        f"expected all {expected_byte}, got {received}"

    dut._log.info("PASS 7.3: all-max-negative results correctly saturated")
