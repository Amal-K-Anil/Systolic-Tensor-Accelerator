# tb_mac_unit.py
#
# cocotb testbench for mac_unit.
#
# mac_unit is a single systolic processing element: on a valid pulse it multiplies
# a_in/b_in (via booth_multiplier, verified separately) and accumulates the result
# into accum_out, and forwards a_in/b_in to a_out/b_out for the next PE. accum_out
# is itself the accumulator register -- fully synchronous, one cycle of latency,
# no separate combinational read-out stage. a_out/b_out only update on a valid
# pulse (not every cycle), matching how the array's own diagonal skew depends on
# forwarding happening exactly in step with real data.
#
# Test cases:
#    1  Reset               -- all outputs zero immediately after reset
#    2  Single accumulate   -- one valid pulse, correct product one cycle later
#    3  Multiple accumulate -- running sum across several valid pulses
#    4  Clear resets all    -- clear zeroes a_out, b_out, and accum_out together
#    5  Clear priority      -- clear and valid same cycle -> clear wins
#    6  a/b hold on !valid  -- a_out/b_out do NOT change when valid=0
#    7  Accum holds         -- accum_out does not change across valid=0 cycles
#    8  Signed extremes     -- most-negative x most-negative and other sign corners
#    9  Sign extension      -- a negative product correctly decrements accum_out
#   10  Clear then resume   -- clear mid-stream, accumulation restarts cleanly at 0
#   11  One-cycle latency   -- accum_out reflects a valid pulse exactly one edge later
#   12  Reset mid-run       -- async reset overrides clear/valid at any point
#   13  Random stress       -- many random (a,b) pairs and valid patterns vs golden model
#
# Run with: make TOPLEVEL=mac_unit

import cocotb
import numpy as np
from cocotb.clock import Clock
from cocotb.triggers import Timer, RisingEdge

DATA_WIDTH  = 8
ACCUM_WIDTH = 21

DATA_MIN = -(1 << (DATA_WIDTH - 1))
DATA_MAX = (1 << (DATA_WIDTH - 1)) - 1
ACCUM_MASK = (1 << ACCUM_WIDTH) - 1
ACCUM_SIGN_BIT = 1 << (ACCUM_WIDTH - 1)


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

def read_a_out(dut):
    return to_signed(int(dut.a_out.value), DATA_WIDTH)

def read_b_out(dut):
    return to_signed(int(dut.b_out.value), DATA_WIDTH)

def read_accum(dut):
    return to_signed(int(dut.accum_out.value), ACCUM_WIDTH)

async def drive(dut, a, b, valid, clear=0):
    dut.a_in.value = a & ((1 << DATA_WIDTH) - 1)
    dut.b_in.value = b & ((1 << DATA_WIDTH) - 1)
    dut.valid.value = valid
    dut.clear.value = clear
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")

async def idle(dut, cycles=1):
    dut.valid.value = 0
    dut.clear.value = 0
    for _ in range(cycles):
        await RisingEdge(dut.clk)
    await Timer(1, unit="ns")


# =========================================================================
# Test 1 -- Reset
# =========================================================================

@cocotb.test()
async def test_reset(dut):
    """All outputs zero immediately after reset."""
    await start_clock(dut)
    await reset_dut(dut)

    assert read_a_out(dut) == 0, "a_out not zero after reset"
    assert read_b_out(dut) == 0, "b_out not zero after reset"
    assert read_accum(dut) == 0, "accum_out not zero after reset"


# =========================================================================
# Test 2 -- Single Accumulate
# =========================================================================

@cocotb.test()
async def test_single_accumulate(dut):
    """One valid pulse produces the correct product one cycle later."""
    await start_clock(dut)
    await reset_dut(dut)

    a, b = 5, -7
    await drive(dut, a, b, valid=1)
    await idle(dut)

    assert read_accum(dut) == a * b, f"expected {a*b}, got {read_accum(dut)}"
    assert read_a_out(dut) == a
    assert read_b_out(dut) == b


# =========================================================================
# Test 3 -- Multiple Accumulate
# =========================================================================

@cocotb.test()
async def test_multiple_accumulate(dut):
    """Running sum across several valid pulses matches the golden model."""
    await start_clock(dut)
    await reset_dut(dut)

    pairs = [(3, 4), (-2, 6), (10, -10), (-8, -8), (1, 1)]
    expected = 0
    for a, b in pairs:
        expected += a * b
        await drive(dut, a, b, valid=1)

    await idle(dut)
    assert read_accum(dut) == expected, f"expected {expected}, got {read_accum(dut)}"


# =========================================================================
# Test 4 -- Clear Resets All Outputs
# =========================================================================

@cocotb.test()
async def test_clear_resets_all_outputs(dut):
    """clear zeroes a_out, b_out, and accum_out together."""
    await start_clock(dut)
    await reset_dut(dut)

    await drive(dut, 6, 6, valid=1)
    assert read_accum(dut) != 0

    await drive(dut, 0, 0, valid=0, clear=1)
    await idle(dut)

    assert read_a_out(dut) == 0
    assert read_b_out(dut) == 0
    assert read_accum(dut) == 0


# =========================================================================
# Test 5 -- Clear Priority Over Valid
# =========================================================================

@cocotb.test()
async def test_clear_priority_over_valid(dut):
    """clear and valid asserted the same cycle -> clear wins, matching the
    RTL's if/else-if structure (no accumulation happens that cycle)."""
    await start_clock(dut)
    await reset_dut(dut)

    await drive(dut, 4, 4, valid=1)
    prior = read_accum(dut)
    assert prior != 0

    # both valid and clear high this cycle
    dut.a_in.value = 9 & 0xFF
    dut.b_in.value = 9 & 0xFF
    dut.valid.value = 1
    dut.clear.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")

    assert read_accum(dut) == 0, "clear did not take priority over valid"
    assert read_a_out(dut) == 0
    assert read_b_out(dut) == 0


# =========================================================================
# Test 6 -- a_out/b_out Hold When !valid
# =========================================================================

@cocotb.test()
async def test_ab_propagate_only_on_valid(dut):
    """a_out/b_out only update on a valid pulse -- unlike a plain pipeline
    register, they do NOT change on cycles where valid=0."""
    await start_clock(dut)
    await reset_dut(dut)

    await drive(dut, 3, -3, valid=1)
    a_before, b_before = read_a_out(dut), read_b_out(dut)

    # drive different values on a_in/b_in but keep valid low
    await drive(dut, 99, -99, valid=0)
    await drive(dut, 50, -50, valid=0)

    assert read_a_out(dut) == a_before, "a_out changed while valid was low"
    assert read_b_out(dut) == b_before, "b_out changed while valid was low"


# =========================================================================
# Test 7 -- accum_out Holds When !valid
# =========================================================================

@cocotb.test()
async def test_no_accum_without_valid(dut):
    """accum_out does not change across valid=0 cycles."""
    await start_clock(dut)
    await reset_dut(dut)

    await drive(dut, 5, 5, valid=1)
    held = read_accum(dut)

    for _ in range(5):
        await drive(dut, 1, 1, valid=0)
        assert read_accum(dut) == held, "accum_out changed without a valid pulse"


# =========================================================================
# Test 8 -- Signed Extremes
# =========================================================================

@cocotb.test()
async def test_signed_extremes(dut):
    """Boundary sign combinations, including the most-negative x
    most-negative corner case."""
    await start_clock(dut)

    cases = [
        (DATA_MIN, DATA_MIN),
        (DATA_MIN, DATA_MAX),
        (DATA_MAX, DATA_MIN),
        (DATA_MAX, DATA_MAX),
        (DATA_MIN, 0),
        (0, DATA_MIN),
        (-1, DATA_MIN),
    ]
    for a, b in cases:
        await reset_dut(dut)
        await drive(dut, a, b, valid=1)
        await idle(dut)
        expected = a * b
        assert read_accum(dut) == expected, f"a={a} b={b}: expected {expected}, got {read_accum(dut)}"


# =========================================================================
# Test 9 -- Sign Extension Into accum_out
# =========================================================================

@cocotb.test()
async def test_sign_extension_into_accum(dut):
    """A negative product correctly decrements accum_out -- verifies the
    product is sign-extended to ACCUM_WIDTH before adding, not
    zero-extended."""
    await start_clock(dut)
    await reset_dut(dut)

    # build up a positive accumulator first
    await drive(dut, 20, 20, valid=1)   # +400
    running = read_accum(dut)
    assert running == 400

    # now accumulate a strongly negative product
    await drive(dut, 20, -20, valid=1)  # -400
    running += 20 * -20
    await idle(dut)

    assert read_accum(dut) == running == 0, f"expected 0, got {read_accum(dut)}"


# =========================================================================
# Test 10 -- Clear Then Resume
# =========================================================================

@cocotb.test()
async def test_clear_then_resume(dut):
    """clear mid-stream, then confirm accumulation restarts cleanly at
    zero, with no residual contribution from before the clear."""
    await start_clock(dut)
    await reset_dut(dut)

    await drive(dut, 12, 12, valid=1)
    await drive(dut, 7, 7, valid=1)
    assert read_accum(dut) != 0

    await drive(dut, 0, 0, valid=0, clear=1)
    await idle(dut)
    assert read_accum(dut) == 0

    a, b = -6, 6
    await drive(dut, a, b, valid=1)
    await idle(dut)
    assert read_accum(dut) == a * b, "accumulation after clear included stale state"


# =========================================================================
# Test 11 -- One-Cycle Latency
# =========================================================================

@cocotb.test()
async def test_accum_one_cycle_latency(dut):
    """accum_out reflects a valid pulse exactly one clock edge later --
    fully registered, not combinational."""
    await start_clock(dut)
    await reset_dut(dut)

    a, b = 9, 3
    dut.a_in.value = a & 0xFF
    dut.b_in.value = b & 0xFF
    dut.valid.value = 1
    dut.clear.value = 0

    # pre-edge: accum_out must NOT reflect this cycle's inputs yet
    await Timer(1, unit="ns")
    assert read_accum(dut) == 0, "accum_out updated before the clock edge"

    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert read_accum(dut) == a * b, "accum_out did not update on the edge"


# =========================================================================
# Test 12 -- Reset Mid-Run
# =========================================================================

@cocotb.test()
async def test_reset_mid_run(dut):
    """Async reset overrides clear/valid at any point in a run, zeroing
    everything regardless of what else is asserted that cycle."""
    await start_clock(dut)
    await reset_dut(dut)

    await drive(dut, 8, 8, valid=1)
    await drive(dut, 4, 4, valid=1)
    assert read_accum(dut) != 0

    # assert reset asynchronously, mid-stream, with valid still high
    dut.rst_n.value = 0
    await Timer(1, unit="ns")
    assert read_a_out(dut) == 0
    assert read_b_out(dut) == 0
    assert read_accum(dut) == 0

    dut.valid.value = 0
    dut.clear.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")

    assert read_accum(dut) == 0, "accum_out not clean after reset recovery"


# =========================================================================
# Test 13 -- Random Stress
# =========================================================================

@cocotb.test()
async def test_random_stress(dut):
    """Many random (a, b) pairs and valid/idle patterns, checked against
    a running numpy golden model. Capped at 32 valid (accumulating) steps
    per run -- ACCUM_WIDTH=21 is only designed to safely hold K<=32
    accumulations (see the ACCUM_WIDTH derivation in the architecture
    spec); going further would induce legitimate accumulator wraparound,
    which is a real overflow condition, not a bug this test should be
    checking for."""
    await start_clock(dut)
    await reset_dut(dut)

    rng = np.random.default_rng(42)
    expected = 0
    valid_steps = 0
    max_valid_steps = 32

    while valid_steps < max_valid_steps:
        do_valid = bool(rng.integers(0, 2))
        a = int(rng.integers(DATA_MIN, DATA_MAX + 1))
        b = int(rng.integers(DATA_MIN, DATA_MAX + 1))

        if do_valid:
            expected += a * b
            valid_steps += 1
            await drive(dut, a, b, valid=1)
        else:
            await drive(dut, a, b, valid=0)

        assert read_accum(dut) == expected, (
            f"mismatch after step: expected {expected}, got {read_accum(dut)}"
        )
