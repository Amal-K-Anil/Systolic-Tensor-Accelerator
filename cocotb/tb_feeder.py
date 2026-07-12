"""
tb_feeder.py — cocotb testbench for feeder.sv
SSCS Chipathon 2026 | Track A | Team Maxilerator | Owner: Irene

"""

import cocotb
from cocotb.clock    import Clock
from cocotb.triggers import RisingEdge, Timer

ARRAY_SIZE   = 8
TILE_BYTES   = 2 * ARRAY_SIZE * ARRAY_SIZE
DRAIN_CYCLES = 2 * (ARRAY_SIZE - 1)
CLK_NS       = 40

EXP_A = [
    [ 1,  0,  0,  0,  0,  0,  0,  0],
    [ 2,  9,  0,  0,  0,  0,  0,  0],
    [ 3, 10, 17,  0,  0,  0,  0,  0],
    [ 4, 11, 18, 25,  0,  0,  0,  0],
    [ 5, 12, 19, 26, 33,  0,  0,  0],
    [ 6, 13, 20, 27, 34, 41,  0,  0],
    [ 7, 14, 21, 28, 35, 42, 49,  0],
    [ 8, 15, 22, 29, 36, 43, 50, 57],
    [ 0, 16, 23, 30, 37, 44, 51, 58],
    [ 0,  0, 24, 31, 38, 45, 52, 59],
    [ 0,  0,  0, 32, 39, 46, 53, 60],
    [ 0,  0,  0,  0, 40, 47, 54, 61],
    [ 0,  0,  0,  0,  0, 48, 55, 62],
    [ 0,  0,  0,  0,  0,  0, 56, 63],
    [ 0,  0,  0,  0,  0,  0,  0, 64],
]
EXP_B = [
    [ 1,  0,  0,  0,  0,  0,  0,  0],
    [ 9,  2,  0,  0,  0,  0,  0,  0],
    [17, 10,  3,  0,  0,  0,  0,  0],
    [25, 18, 11,  4,  0,  0,  0,  0],
    [33, 26, 19, 12,  5,  0,  0,  0],
    [41, 34, 27, 20, 13,  6,  0,  0],
    [49, 42, 35, 28, 21, 14,  7,  0],
    [57, 50, 43, 36, 29, 22, 15,  8],
    [ 0, 58, 51, 44, 37, 30, 23, 16],
    [ 0,  0, 59, 52, 45, 38, 31, 24],
    [ 0,  0,  0, 60, 53, 46, 39, 32],
    [ 0,  0,  0,  0, 61, 54, 47, 40],
    [ 0,  0,  0,  0,  0, 62, 55, 48],
    [ 0,  0,  0,  0,  0,  0, 63, 56],
    [ 0,  0,  0,  0,  0,  0,  0, 64],
]

BASE_MEM = {}
for _r in range(ARRAY_SIZE):
    for _k in range(ARRAY_SIZE):
        BASE_MEM[_r * ARRAY_SIZE + _k] = _r * ARRAY_SIZE + _k + 1
for _k in range(ARRAY_SIZE):
    for _c in range(ARRAY_SIZE):
        BASE_MEM[64 + _k * ARRAY_SIZE + _c] = _k * ARRAY_SIZE + _c + 1

def make_sram(offset=0):
    return {a: (v + offset) & 0xFF for a, v in BASE_MEM.items()}

class SramModel:
    """
    Model of the feeder's SRAM interface, including 3-cycle capture pipeline.
    """
    def __init__(self, mem):
        self.mem = mem
        self.d0 = (0, 0)  # (addr, re) — most recent
        self.d1 = (0, 0)
        self.d2 = (0, 0)  # oldest — this is what we drive

    def pre_tick(self, dut):
        """Drive sram_data = mem[addr_{N-3}] BEFORE awaiting rising edge."""
        addr, re = self.d2
        dut.sram_data.value = self.mem.get(addr, 0) if re else 0

    def post_tick(self, dut):
        """Shift pipeline after sampling. Call AFTER Timer(1ns)."""
        self.d2 = self.d1
        self.d1 = self.d0
        self.d0 = (int(dut.read_addr.value), int(dut.read_en.value))

    def swap(self, new_mem):
        self.mem = new_mem

async def reset(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_NS, units="ns").start())
    dut.rst_n.value      = 0
    dut.start.value = 0
    dut.drain_en.value  = 0
    dut.clear.value      = 0
    dut.sram_data.value  = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

async def tick(dut, sm, start=0, drain_en=0, clear=0):
    """
    One cycle:
      1. sm.pre_tick(): drive sram_data = mem[addr_{N-3}] before rising edge
      2. Drive control inputs
      3. Rising edge fires — FF captures sram_data ✓
      4. Timer 1ns — outputs settle
      5. Sample outputs
      6. sm.post_tick(): shift pipeline with addr_N
    """
    sm.pre_tick(dut)
    dut.start.value = start
    dut.drain_en.value  = drain_en
    dut.clear.value      = clear
    await RisingEdge(dut.clk)
    await Timer(1, units="ns")
    snap = {
        "re":   int(dut.read_en.value),
        "addr": int(dut.read_addr.value),
        "v":    int(dut.valid.value),
        "dd":   int(dut.drain_done.value),
        "a":    [(int(dut.a_in.value) >> (i * 8)) & 0xFF for i in range(ARRAY_SIZE)],
        "b":    [(int(dut.b_in.value) >> (i * 8)) & 0xFF for i in range(ARRAY_SIZE)],
    }
    sm.post_tick(dut)
    return snap

def ok(name, passed):
    tag = "PASS" if passed else "FAIL"
    print(f"[{tag}] {name}")
    assert passed, f"FAILED: {name}"

@cocotb.test()
async def test_reset_state(dut):
    """After rst_n deasserts, all outputs must be zero and feeder idle."""
    await reset(dut)
    await Timer(1, units="ns")
    ok("test_reset_state",
       int(dut.read_en.value)    == 0 and
       int(dut.valid.value)      == 0 and
       int(dut.drain_done.value) == 0 and
       int(dut.a_in.value)       == 0 and
       int(dut.b_in.value)       == 0)

@cocotb.test()
async def test_no_autostart(dut):
    await reset(dut)
    sm    = SramModel(make_sram())
    snaps = [await tick(dut, sm) for _ in range(20)]
    ok("test_no_autostart", all(s["re"] == 0 for s in snaps))

@cocotb.test()
async def test_address_sequence(dut):
    """128 addresses in correct A/B interleaved order per spec Section 5.2."""
    await reset(dut)
    sm = SramModel(make_sram())
    expected = []
    for k in range(ARRAY_SIZE):
        for row in range(ARRAY_SIZE):
            expected.append(row * ARRAY_SIZE + k)
        for col in range(ARRAY_SIZE):
            expected.append(64 + k * ARRAY_SIZE + col)
    got = []
    for i in range(TILE_BYTES + 5):
        s = await tick(dut, sm, start=(1 if i == 0 else 0))
        if s["re"]:
            got.append(s["addr"])
    ok("test_address_sequence", got == expected)

@cocotb.test()
async def test_read_en_self_stop(dut):
    """read_en HIGH for exactly 128 cycles then LOW forever."""
    await reset(dut)
    sm    = SramModel(make_sram())
    snaps = [await tick(dut, sm, start=(1 if i == 0 else 0))
             for i in range(TILE_BYTES + 10)]
    hist  = [s["re"] for s in snaps]
    ones  = [i for i, v in enumerate(hist) if v]
    ok("test_read_en_self_stop",
       len(ones) == TILE_BYTES and
       ones      == list(range(TILE_BYTES)) and
       all(v == 0 for v in hist[TILE_BYTES:]))

@cocotb.test()
async def test_valid_pulse_timing(dut):
    """Exactly ARRAY_SIZE valid pulses, each exactly 16 cycles apart."""
    await reset(dut)
    sm   = SramModel(make_sram())
    vcyc = []
    for i in range(TILE_BYTES + 30):
        s = await tick(dut, sm, start=(1 if i == 0 else 0), drain_en=0)
        if s["v"]:
            vcyc.append(i)
    ok("test_valid_pulse_timing",
       len(vcyc) == ARRAY_SIZE and
       all(vcyc[j + 1] - vcyc[j] == 16 for j in range(ARRAY_SIZE - 1)))

@cocotb.test()
async def test_wavefront_normal(dut):
    """a_in/b_in at each of 8 normal valid pulses must match EXP_A/EXP_B rows 0-7."""
    await reset(dut)
    sm     = SramModel(make_sram())
    pidx   = 0
    passed = True
    for i in range(TILE_BYTES + 30):
        s = await tick(dut, sm, start=(1 if i == 0 else 0), drain_en=0)
        if s["v"] and pidx < ARRAY_SIZE:
            if s["a"] != EXP_A[pidx] or s["b"] != EXP_B[pidx]:
                dut._log.error(
                    f"Normal pulse {pidx}: "
                    f"a_in={s['a']} expected={EXP_A[pidx]} | "
                    f"b_in={s['b']} expected={EXP_B[pidx]}"
                )
                passed = False
            pidx += 1
    ok("test_wavefront_normal", passed and pidx == ARRAY_SIZE)

@cocotb.test()
async def test_drain_phase(dut):
    await reset(dut)
    sm     = SramModel(make_sram())
    normal = 0
    drain_snaps = []
    for i in range(TILE_BYTES + DRAIN_CYCLES + 15):
        s = await tick(dut, sm, start=(1 if i == 0 else 0), drain_en=1)
        if s["v"]:
            if normal < ARRAY_SIZE:
                normal += 1
            else:
                drain_snaps.append((i, s["a"], s["b"]))
    count_ok   = (len(drain_snaps) == DRAIN_CYCLES)
    cycs       = [c for c, _, _ in drain_snaps]
    contiguous = (len(cycs) > 1 and
                  all(cycs[j + 1] - cycs[j] == 1 for j in range(len(cycs) - 1)))
    # Last 7 drain pulses must be all zero
    zero_ok = all(
        x == 0 for _, a, b in drain_snaps[9:] for x in a + b
    )
    if not zero_ok:
        for di, (_, a, b) in enumerate(drain_snaps[9:]):
            if any(x != 0 for x in a + b):
                dut._log.error(f"Drain pulse {di+8} not zero: a_in={a} b_in={b}")
    ok("test_drain_phase", count_ok and contiguous and zero_ok)

@cocotb.test()
async def test_drain_done_timing(dut):
    """drain_done fires exactly once, on the same cycle as the 14th drain pulse."""
    await reset(dut)
    sm    = SramModel(make_sram())
    vcyc  = []
    ddcyc = []
    for i in range(TILE_BYTES + DRAIN_CYCLES + 15):
        s = await tick(dut, sm, start=(1 if i == 0 else 0), drain_en=1)
        if s["v"]:  vcyc.append(i)
        if s["dd"]: ddcyc.append(i)
    ok("test_drain_done_timing",
       len(ddcyc) == 1 and bool(vcyc) and ddcyc[0] == vcyc[-1])

@cocotb.test()
async def test_start_restart(dut):
    """start restarts read_en immediately; skew buffer NOT cleared."""
    await reset(dut)
    sm1 = SramModel(make_sram(0))
    for i in range(TILE_BYTES + 5):
        await tick(dut, sm1, start=(1 if i == 0 else 0), drain_en=0)
    await Timer(1, units="ns")
    skew_nonzero = (int(dut.a_in.value) != 0)
    s = await tick(dut, sm1, start=1)
    restarted = (s["re"] == 1)
    sm2  = SramModel(make_sram(50))
    vcnt = 0
    for _ in range(TILE_BYTES + 30):
        s = await tick(dut, sm2, drain_en=0)
        if s["v"]: vcnt += 1
    ok("test_start_restart",
       skew_nonzero and restarted and vcnt == ARRAY_SIZE)

@cocotb.test()
async def test_clear_full_reset(dut):
    """clear zeros all state; feeder stays idle until next start."""
    await reset(dut)
    sm = SramModel(make_sram())
    for i in range(60):
        await tick(dut, sm, start=(1 if i == 0 else 0))
    await Timer(1, units="ns")
    was_nonzero = (int(dut.a_in.value) != 0)
    await tick(dut, sm, clear=1)
    await Timer(1, units="ns")
    post_ok = (
        int(dut.read_en.value)    == 0 and
        int(dut.valid.value)      == 0 and
        int(dut.drain_done.value) == 0 and
        int(dut.a_in.value)       == 0 and
        int(dut.b_in.value)       == 0
    )
    stays_idle = True
    for _ in range(10):
        s = await tick(dut, sm)
        if s["re"] or s["v"]: stays_idle = False
    ok("test_clear_full_reset", was_nonzero and post_ok and stays_idle)

@cocotb.test()
async def test_two_tile_continuous(dut):
    """Back-to-back tiles: correct pulse counts and drain on last tile."""
    await reset(dut)
    sm1 = SramModel(make_sram(0))
    sm2 = SramModel(make_sram(7))
    v1  = 0
    for i in range(TILE_BYTES + 3):
        s = await tick(dut, sm1, start=(1 if i == 0 else 0), drain_en=0)
        if s["v"]: v1 += 1
    v2 = dd = drain = 0
    for i in range(TILE_BYTES + DRAIN_CYCLES + 10):
        s = await tick(dut, sm2, start=(1 if i == 0 else 0), drain_en=1)
        if s["v"]:
            if v2 < ARRAY_SIZE: v2 += 1
            else:               drain += 1
        if s["dd"]: dd += 1
    ok("test_two_tile_continuous",
       v1    == ARRAY_SIZE   and
       v2    == ARRAY_SIZE   and
       drain == DRAIN_CYCLES and
       dd    == 1)

@cocotb.test()
async def test_valid_no_glitch(dut):
    """valid must never be HIGH on two consecutive cycles during normal operation."""
    await reset(dut)
    sm      = SramModel(make_sram())
    prev    = 0
    ok_flag = True
    for i in range(TILE_BYTES + 20):
        s = await tick(dut, sm, start=(1 if i == 0 else 0), drain_en=0)
        if s["v"] == 1 and prev == 1:
            dut._log.error(f"valid glitch at cycle {i}")
            ok_flag = False
            break
        prev = s["v"]
    ok("test_valid_no_glitch", ok_flag)

@cocotb.test()
async def test_staging_capture_timing(dut):
    """
    Verify staging latency per probe test: addr at tick N → capture at tick N+3.
    A_stage[0]=a_in[7:0], B_stage[0]=b_in[7:0] (zero skew, direct wires).
    3 ticks after addr=0 presented:  a_in[0] must equal sram[0]=101.
    3 ticks after addr=64 presented: b_in[0] must equal sram[64]=201.
    """
    await reset(dut)

    raw_sram = {}
    for a in range(64):
        raw_sram[a] = (101 + a) & 0xFF
    for a in range(64, 128):
        raw_sram[a] = (201 + (a - 64)) & 0xFF

    sm = SramModel(raw_sram)
    exp_A0 = raw_sram[0]    # 101
    exp_B0 = raw_sram[64]   # 201

    addr_0_cycle  = None
    addr_64_cycle = None
    a0_correct    = None
    b0_correct    = None
    cap_pipeline_ok = True

    py_ced1 = 0; py_ph1 = 0; py_pos1 = 0
    py_ced2 = 0; py_ph2 = 0; py_pos2 = 0

    for i in range(TILE_BYTES + 15):
        sm.pre_tick(dut)
        dut.start.value = (1 if i == 0 else 0)
        dut.drain_en.value  = 0
        dut.clear.value      = 0
        await RisingEdge(dut.clk)
        await Timer(1, units="ns")

        re   = int(dut.read_en.value)
        addr = int(dut.read_addr.value)
        ced1 = int(dut.cap_en_d1.value)
        ph1  = int(dut.phase_d1.value)
        pos1 = int(dut.pos_d1.value)

        cap_d2 = py_ced2
        ph_d2  = py_ph2
        pos_d2 = py_pos2

        if re and addr == 0  and addr_0_cycle  is None: addr_0_cycle  = i
        if re and addr == 64 and addr_64_cycle is None: addr_64_cycle = i

        # Capture happens at tick N+3 per probe
        if addr_0_cycle is not None and i == addr_0_cycle + 3:
            got = (int(dut.a_in.value) >> 0) & 0xFF
            a0_correct = (got == exp_A0)
            if not a0_correct:
                dut._log.error(f"A_stage[0] tick {i}: got {got}, expected {exp_A0}")
            if not (cap_d2 == 1 and ph_d2 == 0 and pos_d2 == 0):
                dut._log.error(
                    f"A pipeline tick {i}: cap_d2={cap_d2}(w1) ph_d2={ph_d2}(w0) pos_d2={pos_d2}(w0)"
                )
                cap_pipeline_ok = False

        if addr_64_cycle is not None and i == addr_64_cycle + 3:
            got = (int(dut.b_in.value) >> 0) & 0xFF
            b0_correct = (got == exp_B0)
            if not b0_correct:
                dut._log.error(f"B_stage[0] tick {i}: got {got}, expected {exp_B0}")
            if not (cap_d2 == 1 and ph_d2 == 1 and pos_d2 == 0):
                dut._log.error(
                    f"B pipeline tick {i}: cap_d2={cap_d2}(w1) ph_d2={ph_d2}(w1) pos_d2={pos_d2}(w0)"
                )
                cap_pipeline_ok = False

        sm.post_tick(dut)
        py_ced2 = py_ced1; py_ph2 = py_ph1; py_pos2 = py_pos1
        py_ced1 = ced1; py_ph1 = ph1; py_pos1 = pos1

    ok("test_staging_capture_timing",
       a0_correct is not None and b0_correct is not None and
       a0_correct and b0_correct and cap_pipeline_ok)

@cocotb.test()
async def test_staging_phase_separation(dut):
    """A bytes never land in B_stage and vice versa; pos sequences correctly."""
    await reset(dut)

    raw_sram = {}
    for a in range(64):
        raw_sram[a] = 10 + a
    for a in range(64, 128):
        raw_sram[a] = (200 + (a - 64)) & 0xFF

    sm = SramModel(raw_sram)
    passed    = True
    a_pos_seq = []
    b_pos_seq = []
    py_ced1 = 0; py_ph1 = 0; py_pos1 = 0

    for i in range(TILE_BYTES + 10):
        sm.pre_tick(dut)
        dut.start.value = (1 if i == 0 else 0)
        dut.drain_en.value  = 0
        dut.clear.value      = 0
        await RisingEdge(dut.clk)
        await Timer(1, units="ns")

        ced1 = int(dut.cap_en_d1.value)
        ph1  = int(dut.phase_d1.value)
        pos1 = int(dut.pos_d1.value)

        cap_d2 = py_ced1; ph_d2 = py_ph1; pos_d2 = py_pos1

        if cap_d2:
            a_val = (int(dut.a_in.value) >> 0) & 0xFF
            b_val = (int(dut.b_in.value) >> 0) & 0xFF
            if ph_d2 == 0:
                a_pos_seq.append(pos_d2)
                if a_val != 0 and not (10 <= a_val <= 73):
                    dut._log.error(f"Cycle {i}: A-phase but a_in[0]={a_val} not in [10,73]")
                    passed = False
            else:
                b_pos_seq.append(pos_d2)
                if not (b_val == 0 or (200 <= b_val <= 255) or b_val <= 7):
                    dut._log.error(f"Cycle {i}: B-phase but b_in[0]={b_val} not in B-range")
                    passed = False

        sm.post_tick(dut)
        py_ced1 = ced1; py_ph1 = ph1; py_pos1 = pos1

    exp_pos_seq = list(range(ARRAY_SIZE)) * ARRAY_SIZE
    if a_pos_seq != exp_pos_seq:
        dut._log.error(f"A pos_d2: got {a_pos_seq}, expected {exp_pos_seq}")
        passed = False
    if b_pos_seq != exp_pos_seq:
        dut._log.error(f"B pos_d2: got {b_pos_seq}, expected {exp_pos_seq}")
        passed = False

    ok("test_staging_phase_separation", passed)


# ── Test 15: back-to-back tile wavefront ──────────────────────────────────────
@cocotb.test()
async def test_back_to_back_tiles(dut):
    """
    Verify back-to-back tile wavefront (2 tiles, same A/B = 1..64 row-major).
    Verified against feeder_8x8_150_cycle_trace_updated.xlsx.

    Tile 1 (drain_en=0, 8 normal valids, no drain):
      Standard diagonal wavefront — identical to EXP_A[0..7] / EXP_B[0..7].

    Tile 2 (drain_en=1, 8 normal valids + drain):
      Skew carries tile 1 tail data into tile 2. Deep rows (large i) still
      drain tile 1's values while shallow rows start fresh with tile 2's data.
      Drain: 14 contiguous pulses, last 7 all zero.
    """
    await reset(dut)

    EXP_T1_A = [
        [ 1,  0,  0,  0,  0,  0,  0,  0],
        [ 2,  9,  0,  0,  0,  0,  0,  0],
        [ 3, 10, 17,  0,  0,  0,  0,  0],
        [ 4, 11, 18, 25,  0,  0,  0,  0],
        [ 5, 12, 19, 26, 33,  0,  0,  0],
        [ 6, 13, 20, 27, 34, 41,  0,  0],
        [ 7, 14, 21, 28, 35, 42, 49,  0],
        [ 8, 15, 22, 29, 36, 43, 50, 57],
    ]
    EXP_T1_B = [
        [ 1,  0,  0,  0,  0,  0,  0,  0],
        [ 9,  2,  0,  0,  0,  0,  0,  0],
        [17, 10,  3,  0,  0,  0,  0,  0],
        [25, 18, 11,  4,  0,  0,  0,  0],
        [33, 26, 19, 12,  5,  0,  0,  0],
        [41, 34, 27, 20, 13,  6,  0,  0],
        [49, 42, 35, 28, 21, 14,  7,  0],
        [57, 50, 43, 36, 29, 22, 15,  8],
    ]
    EXP_T2_A = [
        [ 1, 16, 23, 30, 37, 44, 51, 58],
        [ 2,  9, 24, 31, 38, 45, 52, 59],
        [ 3, 10, 17, 32, 39, 46, 53, 60],
        [ 4, 11, 18, 25, 40, 47, 54, 61],
        [ 5, 12, 19, 26, 33, 48, 55, 62],
        [ 6, 13, 20, 27, 34, 41, 56, 63],
        [ 7, 14, 21, 28, 35, 42, 49, 64],
        [ 8, 15, 22, 29, 36, 43, 50, 57],
    ]
    EXP_T2_B = [
        [ 1, 58, 51, 44, 37, 30, 23, 16],
        [ 9,  2, 59, 52, 45, 38, 31, 24],
        [17, 10,  3, 60, 53, 46, 39, 32],
        [25, 18, 11,  4, 61, 54, 47, 40],
        [33, 26, 19, 12,  5, 62, 55, 48],
        [41, 34, 27, 20, 13,  6, 63, 56],
        [49, 42, 35, 28, 21, 14,  7, 64],
        [57, 50, 43, 36, 29, 22, 15,  8],
    ]

    sm     = SramModel(make_sram())
    passed = True

    # ── Tile 1: drain_en=0, 8 normal valids, no drain ───────────────────────
    pidx = 0
    for i in range(TILE_BYTES + 5):
        s = await tick(dut, sm, start=(1 if i == 0 else 0), drain_en=0)
        if s["v"] and pidx < ARRAY_SIZE:
            if s["a"] != EXP_T1_A[pidx] or s["b"] != EXP_T1_B[pidx]:
                dut._log.error(
                    f"T1 pulse {pidx}: "
                    f"a_in={s['a']} expected={EXP_T1_A[pidx]} | "
                    f"b_in={s['b']} expected={EXP_T1_B[pidx]}"
                )
                passed = False
            pidx += 1
    if pidx != ARRAY_SIZE:
        dut._log.error(f"Tile 1: {pidx} normal valids, expected {ARRAY_SIZE}")
        passed = False

    # ── Tile 2: swap immediately, drain_en=1 ────────────────────────────────
    pidx = 0
    drain_snaps = []
    for i in range(TILE_BYTES + DRAIN_CYCLES + 15):
        s = await tick(dut, sm, start=(1 if i == 0 else 0), drain_en=1)
        if s["v"]:
            if pidx < ARRAY_SIZE:
                print(f"T2 pulse {pidx}: a={s[chr(97)]} b={s[chr(98)]}")
                if s["a"] != EXP_T2_A[pidx] or s["b"] != EXP_T2_B[pidx]:
                    dut._log.error(
                        f"T2 pulse {pidx}: "
                        f"a_in={s['a']} expected={EXP_T2_A[pidx]} | "
                        f"b_in={s['b']} expected={EXP_T2_B[pidx]}"
                    )
                    passed = False
                pidx += 1
            else:
                drain_snaps.append((i, s["a"], s["b"]))

    if pidx != ARRAY_SIZE:
        dut._log.error(f"Tile 2: {pidx} normal valids, expected {ARRAY_SIZE}")
        passed = False

    # Drain: 14 contiguous, last 7 all zero (account for 1-pulse staging delay)
    if len(drain_snaps) != DRAIN_CYCLES:
        dut._log.error(f"T2 drain: {len(drain_snaps)} pulses, expected {DRAIN_CYCLES}")
        passed = False
    else:
        cycs = [c for c,_,_ in drain_snaps]
        if not all(cycs[j+1]-cycs[j]==1 for j in range(len(cycs)-1)):
            dut._log.error("T2 drain not contiguous")
            passed = False
        for di, (_, a, b) in enumerate(drain_snaps[8:]):
            if any(x != 0 for x in a + b):
                dut._log.error(f"T2 drain pulse {di+9} not zero: a={a} b={b}")
                passed = False

    ok("test_back_to_back_tiles", passed)