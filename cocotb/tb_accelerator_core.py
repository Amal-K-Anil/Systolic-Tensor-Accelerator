# tb_accelerator_core.py
#
# cocotb integration testbench for accelerator_core.sv
# Tests end-to-end tiled INT8 matrix multiplication.
# Uses numpy as software golden model for result verification.
#
# Simulator: Icarus Verilog (iverilog)
# Run with: make TOPLEVEL=accelerator_core (from cocotb/)

import cocotb
import numpy as np
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer

# -----------------------------------------------------------------------
# Parameters (must match accelerator_core.sv)
# -----------------------------------------------------------------------
ARRAY_SIZE  = 8
DATA_WIDTH  = 8
ACCUM_WIDTH = 21
CLK_PERIOD  = 40  # ns (25 MHz)

# -----------------------------------------------------------------------
# Helper: start clock
# -----------------------------------------------------------------------
async def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD, units="ns").start())

# -----------------------------------------------------------------------
# Helper: reset DUT
# -----------------------------------------------------------------------
async def reset_dut(dut):
    dut.rst_n.value     = 0
    dut.valid_in.value  = 0
    dut.tile_done.value = 0
    dut.last_pass.value = 0
    dut.data_in.value   = 0
    dut.ready_out.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

# -----------------------------------------------------------------------
# Helper: numpy golden model
# Computes C = A x B using INT8 inputs, returns INT8 saturated results
# -----------------------------------------------------------------------
def golden_model(A, B):
    # Full precision accumulation
    C = A.astype(np.int32) @ B.astype(np.int32)
    # Saturate to INT8
    C = np.clip(C, -128, 127).astype(np.int8)
    return C

# -----------------------------------------------------------------------
# Helper: prepare tile stream
# Host sends data sequentially to SRAM:
#   Bytes 0-63:   A matrix row by row
#   Bytes 64-127: B matrix row by row
# Feeder handles column/row reordering via SRAM address calculation.
# Total: 2 x ARRAY_SIZE x ARRAY_SIZE = 128 bytes per tile
# -----------------------------------------------------------------------
def prepare_tile(A_tile, B_tile):
    stream = []
    # A matrix: row by row (bytes 0-63)
    for i in range(ARRAY_SIZE):
        for j in range(ARRAY_SIZE):
            stream.append(int(A_tile[i, j]) & 0xFF)
    # B matrix: row by row (bytes 64-127)
    for i in range(ARRAY_SIZE):
        for j in range(ARRAY_SIZE):
            stream.append(int(B_tile[i, j]) & 0xFF)
    return stream

# -----------------------------------------------------------------------
# Helper: send one tile to DUT
# Handles ready_in handshake and tile_done assertion
# -----------------------------------------------------------------------
async def send_tile(dut, A_tile, B_tile, last_pass=False, stall_at=None):
    stream = prepare_tile(A_tile, B_tile)
    BYTES_PER_PASS = 2 * ARRAY_SIZE * ARRAY_SIZE  # 128

    # Wait for ready_in permission
    timeout = 500
    for _ in range(timeout):
        if dut.ready_in.value == 1:
            break
        await RisingEdge(dut.clk)
    else:
        assert False, "Timeout waiting for ready_in"

    dut.last_pass.value = 1 if last_pass else 0

    for byte_idx, byte_val in enumerate(stream):
        # Optional host stall
        if stall_at is not None and byte_idx == stall_at:
            dut.valid_in.value  = 0
            dut.tile_done.value = 0
            for _ in range(10):
                await RisingEdge(dut.clk)

        is_last = (byte_idx == BYTES_PER_PASS - 1)
        dut.valid_in.value  = 1
        dut.data_in.value   = byte_val
        dut.tile_done.value = 1 if is_last else 0
        await RisingEdge(dut.clk)

    dut.valid_in.value  = 0
    dut.tile_done.value = 0
    dut.last_pass.value = 0

# -----------------------------------------------------------------------
# Helper: receive 64 results from DUT
# Returns list of signed INT8 results in row-major order
# -----------------------------------------------------------------------
async def receive_results(dut, backpressure_at=None):
    results = []
    timeout = 1000
    count   = 0

    for _ in range(timeout):
        # Optional backpressure
        if backpressure_at is not None and count == backpressure_at:
            dut.ready_out.value = 0
            for _ in range(5):
                await RisingEdge(dut.clk)
            dut.ready_out.value = 1

        await Timer(1, units="ns")

        if dut.valid_out.value == 1 and dut.ready_out.value == 1:
            raw = int(dut.data_out.value)
            # Convert to signed INT8
            if raw >= 128:
                raw -= 256
            results.append(raw)
            count += 1
            if count == ARRAY_SIZE * ARRAY_SIZE:
                await RisingEdge(dut.clk)
                break

        await RisingEdge(dut.clk)
    else:
        assert False, f"Timeout receiving results (got {count}/{ARRAY_SIZE*ARRAY_SIZE})"

    return results

# -----------------------------------------------------------------------
# Helper: compare DUT results vs numpy golden model
# -----------------------------------------------------------------------
def compare_results(dut_results, C_expected, test_name):
    C_flat = C_expected.flatten().tolist()
    mismatches = []
    for idx, (got, exp) in enumerate(zip(dut_results, C_flat)):
        if got != exp:
            row = idx // ARRAY_SIZE
            col = idx  % ARRAY_SIZE
            mismatches.append(f"  C[{row}][{col}]: got={got}, expected={exp}")
    if mismatches:
        assert False, f"{test_name} FAILED:\n" + "\n".join(mismatches)

# -----------------------------------------------------------------------
# Test 1: Single pass (N=8, k=1)
# One 8x8 tile — simplest case
# -----------------------------------------------------------------------
@cocotb.test()
async def test_single_pass(dut):
    """Single pass 8x8 matrix multiply — basic functional test."""
    await start_clock(dut)
    await reset_dut(dut)

    # Generate random INT8 matrices
    np.random.seed(42)
    A = np.random.randint(-128, 128, (ARRAY_SIZE, ARRAY_SIZE), dtype=np.int8)
    B = np.random.randint(-128, 128, (ARRAY_SIZE, ARRAY_SIZE), dtype=np.int8)
    C_expected = golden_model(A, B)

    # Send tile (last_pass=True — only one pass)
    await send_tile(dut, A, B, last_pass=True)

    # Receive and verify results
    results = await receive_results(dut)
    compare_results(results, C_expected, "test_single_pass")

    dut._log.info("PASS: test_single_pass")

# -----------------------------------------------------------------------
# Test 2: Multi-pass (N=16, k=2)
# Two 8x8 tiles — verifies accumulation across passes
# -----------------------------------------------------------------------
@cocotb.test()
async def test_multi_pass_k2(dut):
    """Two-pass 16x16 matrix multiply — verifies ping-pong and accumulation."""
    await start_clock(dut)
    await reset_dut(dut)

    np.random.seed(123)
    N = 16
    A = np.random.randint(-64, 64, (ARRAY_SIZE, N), dtype=np.int8)
    B = np.random.randint(-64, 64, (N, ARRAY_SIZE), dtype=np.int8)
    C_expected = golden_model(A, B)

    # Split into k=2 passes
    # Pass 0: A[:,0:8] x B[0:8,:]
    # Pass 1: A[:,8:16] x B[8:16,:]
    for k in range(N // ARRAY_SIZE):
        A_tile = A[:, k*ARRAY_SIZE:(k+1)*ARRAY_SIZE]
        B_tile = B[k*ARRAY_SIZE:(k+1)*ARRAY_SIZE, :]
        is_last = (k == N // ARRAY_SIZE - 1)
        await send_tile(dut, A_tile, B_tile, last_pass=is_last)

    results = await receive_results(dut)
    compare_results(results, C_expected, "test_multi_pass_k2")

    dut._log.info("PASS: test_multi_pass_k2")

# -----------------------------------------------------------------------
# Test 3: Multi-pass (N=32, k=4)
# Four 8x8 tiles — verifies accumulation over more passes
# -----------------------------------------------------------------------
@cocotb.test()
async def test_multi_pass_k4(dut):
    """Four-pass 32x32 matrix multiply — verifies multi-tile accumulation."""
    await start_clock(dut)
    await reset_dut(dut)

    np.random.seed(456)
    N = 32
    A = np.random.randint(-32, 32, (ARRAY_SIZE, N), dtype=np.int8)
    B = np.random.randint(-32, 32, (N, ARRAY_SIZE), dtype=np.int8)
    C_expected = golden_model(A, B)

    for k in range(N // ARRAY_SIZE):
        A_tile = A[:, k*ARRAY_SIZE:(k+1)*ARRAY_SIZE]
        B_tile = B[k*ARRAY_SIZE:(k+1)*ARRAY_SIZE, :]
        is_last = (k == N // ARRAY_SIZE - 1)
        await send_tile(dut, A_tile, B_tile, last_pass=is_last)

    results = await receive_results(dut)
    compare_results(results, C_expected, "test_multi_pass_k4")

    dut._log.info("PASS: test_multi_pass_k4")

# -----------------------------------------------------------------------
# Test 4: Back-to-back computations
# Two consecutive 8x8 multiplications — verifies clean reset between runs
# -----------------------------------------------------------------------
@cocotb.test()
async def test_back_to_back(dut):
    """Two consecutive 8x8 multiplications — verifies clean state reset."""
    await start_clock(dut)
    await reset_dut(dut)

    np.random.seed(789)

    for run in range(2):
        A = np.random.randint(-128, 128, (ARRAY_SIZE, ARRAY_SIZE), dtype=np.int8)
        B = np.random.randint(-128, 128, (ARRAY_SIZE, ARRAY_SIZE), dtype=np.int8)
        C_expected = golden_model(A, B)

        await send_tile(dut, A, B, last_pass=True)
        results = await receive_results(dut)
        compare_results(results, C_expected, f"test_back_to_back run {run}")

    dut._log.info("PASS: test_back_to_back")

# -----------------------------------------------------------------------
# Test 5: Host stall mid-tile
# valid_in goes LOW for 10 cycles mid-tile — verifies write_addr holds
# -----------------------------------------------------------------------
@cocotb.test()
async def test_host_stall(dut):
    """Host stalls mid-tile — verifies write_addr holds and resumes correctly."""
    await start_clock(dut)
    await reset_dut(dut)

    np.random.seed(111)
    A = np.random.randint(-128, 128, (ARRAY_SIZE, ARRAY_SIZE), dtype=np.int8)
    B = np.random.randint(-128, 128, (ARRAY_SIZE, ARRAY_SIZE), dtype=np.int8)
    C_expected = golden_model(A, B)

    # Stall at byte 50
    await send_tile(dut, A, B, last_pass=True, stall_at=50)
    results = await receive_results(dut)
    compare_results(results, C_expected, "test_host_stall")

    dut._log.info("PASS: test_host_stall")

# -----------------------------------------------------------------------
# Test 6: Output backpressure
# ready_out goes LOW mid-output — verifies valid/ready handshake
# -----------------------------------------------------------------------
@cocotb.test()
async def test_output_backpressure(dut):
    """Output backpressure — verifies ready_out/valid_out handshake."""
    await start_clock(dut)
    await reset_dut(dut)

    np.random.seed(222)
    A = np.random.randint(-128, 128, (ARRAY_SIZE, ARRAY_SIZE), dtype=np.int8)
    B = np.random.randint(-128, 128, (ARRAY_SIZE, ARRAY_SIZE), dtype=np.int8)
    C_expected = golden_model(A, B)

    await send_tile(dut, A, B, last_pass=True)

    # Apply backpressure at result 30
    results = await receive_results(dut, backpressure_at=30)
    compare_results(results, C_expected, "test_output_backpressure")

    dut._log.info("PASS: test_output_backpressure")

# -----------------------------------------------------------------------
# Test 7: Known values test
# Uses fixed matrices for easy manual verification
# -----------------------------------------------------------------------
@cocotb.test()
async def test_known_values(dut):
    """Known fixed-value matrix multiply — easy to manually verify."""
    await start_clock(dut)
    await reset_dut(dut)

    # Identity matrix x Identity matrix = Identity matrix
    A = np.eye(ARRAY_SIZE, dtype=np.int8)
    B = np.eye(ARRAY_SIZE, dtype=np.int8)
    C_expected = golden_model(A, B)

    await send_tile(dut, A, B, last_pass=True)
    results = await receive_results(dut)
    compare_results(results, C_expected, "test_known_values (identity)")

    # Wait for reset to IDLE
    for _ in range(10):
        await RisingEdge(dut.clk)

    # All ones matrix
    A = np.ones((ARRAY_SIZE, ARRAY_SIZE), dtype=np.int8)
    B = np.ones((ARRAY_SIZE, ARRAY_SIZE), dtype=np.int8)
    C_expected = golden_model(A, B)

    await send_tile(dut, A, B, last_pass=True)
    results = await receive_results(dut)
    compare_results(results, C_expected, "test_known_values (all ones)")

    dut._log.info("PASS: test_known_values")

# -----------------------------------------------------------------------
# Test 8: Saturation test
# Large values that should saturate to INT8 bounds
# -----------------------------------------------------------------------
@cocotb.test()
async def test_saturation(dut):
    """Saturation test — large products that clip to INT8 bounds."""
    await start_clock(dut)
    await reset_dut(dut)

    # Max positive values → products saturate to 127
    A = np.full((ARRAY_SIZE, ARRAY_SIZE), 127, dtype=np.int8)
    B = np.full((ARRAY_SIZE, ARRAY_SIZE), 127, dtype=np.int8)
    C_expected = golden_model(A, B)

    await send_tile(dut, A, B, last_pass=True)
    results = await receive_results(dut)
    compare_results(results, C_expected, "test_saturation (positive)")

    # Wait for reset
    for _ in range(10):
        await RisingEdge(dut.clk)

    # Max negative × positive → saturates to -128
    A = np.full((ARRAY_SIZE, ARRAY_SIZE), -128, dtype=np.int8)
    B = np.full((ARRAY_SIZE, ARRAY_SIZE),  127, dtype=np.int8)
    C_expected = golden_model(A, B)

    await send_tile(dut, A, B, last_pass=True)
    results = await receive_results(dut)
    compare_results(results, C_expected, "test_saturation (negative)")

    dut._log.info("PASS: test_saturation")
