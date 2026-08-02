"""
Full cycle-by-cycle feeder verification and trace generation.

This testbench checks BOTH cases requested by the Excel workbook:
  1. one final tile
  2. two back-to-back tiles, with no clear between tiles

Every displayed clock is checked for:
  - read_en, read_addr, read_counter and reading
  - sram_data returned by the 2-cycle SRAM model
  - every A_stage and B_stage register
  - every physical skew_A and skew_B register (28 per side for N=8)
  - every a_in and b_in lane, including valid=0 clocks
  - normal-valid, drain-active, drain counter and drain_done

Additionally, every clock is printed as ACTUAL versus EXPECTED and written to CSV.
On valid clocks, a_in/b_in are also checked against the diagonal wavefront in
"Valid Summary" from the Excel workbook.

B-symbol byte encoding used by the hardware model:
  a..z  -> byte 1..26
  "1".."38" -> byte 27..64
This preserves the workbook statement that all 64 B entries are distinct.
The trace printer decodes those bytes back to the original Excel symbols.

Important workbook notes:
  - The back-to-back sheet omits cycle label 261. RTL drain cycle 1 is cycle 261.
  - The back-to-back sheet has b_in[7]="36" at cycle 244; the correct value is
    "38" from B[7][7].
  - The workbook's a_in/b_in values during valid=0 are presentation values.
    This test checks the real RTL outputs every cycle against an independent
    register-level reference model, and checks Excel wavefront values on every
    valid clock (the only clocks consumed by the systolic array).
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

CLK_NS = 40
N = 8
TILE_BYTES = 2 * N * N
SKEW_DEPTH = N * (N - 1) // 2
DRAIN_CYCLES = 2 * (N - 1)
TRACE_ALL = os.getenv("TRACE_ALL", "1") != "0"
TRACE_DIR = Path(os.getenv("TRACE_DIR", "traces"))


# =============================================================================
# Excel matrices and distinct byte encoding
# =============================================================================
A_MATRIX = [[r * N + c + 1 for c in range(N)] for r in range(N)]


def b_id_to_symbol(value: int) -> str:
    """Decode unique B byte ID 1..64 to the workbook symbol."""
    if value == 0:
        return "0"
    if 1 <= value <= 26:
        return chr(ord("a") + value - 1)
    if 27 <= value <= 64:
        return str(value - 26)
    return f"0x{value:02X}"


# Byte IDs 1..64 represent a..z, then 1..38.
B_MATRIX = [[r * N + c + 1 for c in range(N)] for r in range(N)]


def build_sram_image() -> Dict[int, int]:
    image: Dict[int, int] = {}
    for r in range(N):
        for c in range(N):
            image[r * N + c] = A_MATRIX[r][c]
            image[N * N + r * N + c] = B_MATRIX[r][c]
    return image


SRAM_IMAGE = build_sram_image()


def tile_vectors() -> Tuple[List[List[int]], List[List[int]]]:
    a_vectors = [[A_MATRIX[row][k] for row in range(N)] for k in range(N)]
    b_vectors = [[B_MATRIX[k][col] for col in range(N)] for k in range(N)]
    return a_vectors, b_vectors


A_TILE_VECTORS, B_TILE_VECTORS = tile_vectors()


def expected_wavefront(
    a_vectors: Sequence[Sequence[int]],
    b_vectors: Sequence[Sequence[int]],
    event_index: int,
) -> Tuple[List[int], List[int]]:
    """Diagonal wavefront. Lane i is delayed by i valid events."""
    out_a: List[int] = []
    out_b: List[int] = []
    for lane in range(N):
        src = event_index - lane
        if 0 <= src < len(a_vectors):
            out_a.append(int(a_vectors[src][lane]) & 0xFF)
            out_b.append(int(b_vectors[src][lane]) & 0xFF)
        else:
            out_a.append(0)
            out_b.append(0)
    return out_a, out_b


def expected_read_addr(read_counter: int) -> int:
    pos = read_counter & (N - 1)
    phase = (read_counter >> 3) & 1
    k = read_counter >> 4
    if phase == 0:
        return pos * N + k
    return N * N + k * N + pos


def unpack_bytes(packed: int, count: int) -> List[int]:
    return [(packed >> (8 * i)) & 0xFF for i in range(count)]


def fmt_a(values: Sequence[int]) -> str:
    return "[" + ",".join(str(v) for v in values) + "]"


def fmt_b(values: Sequence[int]) -> str:
    return "[" + ",".join(b_id_to_symbol(v) for v in values) + "]"


def fmt_skew(values: Sequence[int], is_b: bool = False) -> str:
    # Physical flattened order: row1 stage0, row2 stages0..1, ..., row7.
    formatter = b_id_to_symbol if is_b else str
    rows: List[str] = []
    base = 0
    for row in range(1, N):
        row_values = values[base : base + row]
        rows.append(f"r{row}:" + "/".join(formatter(v) for v in row_values))
        base += row
    return "{" + " ".join(rows) + "}"


# =============================================================================
# 2-cycle SRAM response source
# =============================================================================
@dataclass(frozen=True)
class ReadRequest:
    enabled: bool
    address: int


class SramLatency2:
    def __init__(self, image: Dict[int, int]):
        self.image = image
        self.requests: List[ReadRequest] = []

    def value_for_cycle(self, cycle: int) -> Tuple[int, str]:
        source_cycle = cycle - 2
        if source_cycle < 0:
            return 0, "warmup"
        request = self.requests[source_cycle]
        if not request.enabled:
            return 0, "idle"
        value = self.image.get(request.address, 0)
        if request.address < N * N:
            return value, f"A@{request.address}"
        return value, f"B@{request.address}({b_id_to_symbol(value)})"

    def capture_request(self, enabled: bool, address: int) -> None:
        self.requests.append(ReadRequest(enabled=enabled, address=address))


# =============================================================================
# Independent register-level feeder reference model
# =============================================================================
@dataclass
class RefState:
    reading: int = 0
    read_counter: int = 0
    current_tile_final: int = 0

    cap_en_d1: int = 0
    phase_d1: int = 0
    pos_d1: int = 0
    normal_valid: int = 0

    drain_active: int = 0
    drain_counter: int = 0
    drain_done: int = 0

    a_stage: List[int] = field(default_factory=lambda: [0] * N)
    b_stage: List[int] = field(default_factory=lambda: [0] * N)
    skew_a: List[int] = field(default_factory=lambda: [0] * SKEW_DEPTH)
    skew_b: List[int] = field(default_factory=lambda: [0] * SKEW_DEPTH)

    def read_addr(self) -> int:
        return expected_read_addr(self.read_counter)

    def a_in(self) -> List[int]:
        out = [self.a_stage[0]]
        for lane in range(1, N):
            tail = lane * (lane - 1) // 2 + lane - 1
            out.append(self.skew_a[tail])
        return out

    def b_in(self) -> List[int]:
        out = [self.b_stage[0]]
        for lane in range(1, N):
            tail = lane * (lane - 1) // 2 + lane - 1
            out.append(self.skew_b[tail])
        return out

    def valid(self) -> int:
        return int(bool(self.normal_valid or self.drain_active))

    def step(self, *, start: int, drain_en: int, clear: int, sram_data: int) -> None:
        """Advance one rising edge using nonblocking-assignment semantics."""
        old = RefState(
            reading=self.reading,
            read_counter=self.read_counter,
            current_tile_final=self.current_tile_final,
            cap_en_d1=self.cap_en_d1,
            phase_d1=self.phase_d1,
            pos_d1=self.pos_d1,
            normal_valid=self.normal_valid,
            drain_active=self.drain_active,
            drain_counter=self.drain_counter,
            drain_done=self.drain_done,
            a_stage=self.a_stage.copy(),
            b_stage=self.b_stage.copy(),
            skew_a=self.skew_a.copy(),
            skew_b=self.skew_b.copy(),
        )

        if clear:
            self.reading = 0
            self.read_counter = 0
            self.current_tile_final = 0
            self.cap_en_d1 = 0
            self.phase_d1 = 0
            self.pos_d1 = 0
            self.normal_valid = 0
            self.drain_active = 0
            self.drain_counter = 0
            self.drain_done = 0
            self.a_stage = [0] * N
            self.b_stage = [0] * N
            self.skew_a = [0] * SKEW_DEPTH
            self.skew_b = [0] * SKEW_DEPTH
            return

        old_phase_now = (old.read_counter >> 3) & 1
        old_pos_now = old.read_counter & (N - 1)

        # Read sequencer.
        if start:
            self.reading = 1
            self.read_counter = 0
            self.current_tile_final = int(bool(drain_en))
        elif old.reading:
            if old.read_counter == TILE_BYTES - 1:
                self.reading = 0
                self.read_counter = old.read_counter
            else:
                self.reading = 1
                self.read_counter = old.read_counter + 1

        # Metadata shadow and normal valid.
        self.cap_en_d1 = old.reading
        if old.reading:
            self.phase_d1 = old_phase_now
            self.pos_d1 = old_pos_now
        self.normal_valid = int(
            bool(old.cap_en_d1 and old.phase_d1 and old.pos_d1 == N - 1)
        )

        drain_begin = int(
            bool(
                old.normal_valid
                and not old.reading
                and old.current_tile_final
                and not old.drain_active
            )
        )

        # Drain control.
        self.drain_done = 0
        if drain_begin:
            self.drain_active = 1
            self.drain_counter = 0
        elif old.drain_active:
            if old.drain_counter == DRAIN_CYCLES - 1:
                self.drain_active = 0
                self.drain_counter = old.drain_counter
                self.drain_done = 1
            else:
                self.drain_active = 1
                self.drain_counter = old.drain_counter + 1

        # Staging registers.
        if drain_begin:
            self.a_stage = [0] * N
            self.b_stage = [0] * N
        elif old.cap_en_d1:
            if old.phase_d1:
                self.b_stage[old.pos_d1] = sram_data & 0xFF
            else:
                self.a_stage[old.pos_d1] = sram_data & 0xFF

        # Physical triangular skew registers.
        if old.normal_valid or old.drain_active:
            next_a = old.skew_a.copy()
            next_b = old.skew_b.copy()
            for row in range(1, N):
                base = row * (row - 1) // 2
                next_a[base] = old.a_stage[row]
                next_b[base] = old.b_stage[row]
                for depth in range(1, row):
                    next_a[base + depth] = old.skew_a[base + depth - 1]
                    next_b[base + depth] = old.skew_b[base + depth - 1]
            self.skew_a = next_a
            self.skew_b = next_b


# =============================================================================
# Trace/check helpers
# =============================================================================
async def reset_dut(dut) -> None:
    dut.rst_n.value = 0

    dut.data_in.value = 0
    dut.valid_in.value = 0
    dut.tile_done.value = 0
    dut.last_pass.value = 0
    dut.ready_out.value = 0

    for _ in range(4):
        await RisingEdge(dut.clk)

    dut.rst_n.value = 1

    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")

    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")


def get_actual(dut) -> Dict[str, object]:
    return {
        "read_en": int(dut.read_en.value),
        "read_addr": int(dut.read_addr.value),
        "sram_data": int(dut.sram_data.value),
        "a_stage": unpack_bytes(int(dut.dbg_a_stage.value), N),
        "b_stage": unpack_bytes(int(dut.dbg_b_stage.value), N),
        "skew_a": unpack_bytes(int(dut.dbg_skew_a.value), SKEW_DEPTH),
        "skew_b": unpack_bytes(int(dut.dbg_skew_b.value), SKEW_DEPTH),
        "a_in": unpack_bytes(int(dut.a_in.value), N),
        "b_in": unpack_bytes(int(dut.b_in.value), N),
        "valid": int(dut.valid.value),
        "drain_done": int(dut.drain_done.value),
        "read_counter": int(dut.dbg_read_counter.value),
        "reading": int(dut.dbg_reading.value),
        "normal_valid": int(dut.dbg_normal_valid.value),
        "drain_active": int(dut.dbg_drain_active.value),
        "drain_counter": int(dut.dbg_drain_counter.value),
        "tile_final": int(dut.dbg_current_tile_final.value),
    }


def get_expected(ref: RefState, sram_data: int) -> Dict[str, object]:
    return {
        "read_en": ref.reading,
        "read_addr": ref.read_addr(),
        "sram_data": sram_data,
        "a_stage": ref.a_stage.copy(),
        "b_stage": ref.b_stage.copy(),
        "skew_a": ref.skew_a.copy(),
        "skew_b": ref.skew_b.copy(),
        "a_in": ref.a_in(),
        "b_in": ref.b_in(),
        "valid": ref.valid(),
        "drain_done": ref.drain_done,
        "read_counter": ref.read_counter,
        "reading": ref.reading,
        "normal_valid": ref.normal_valid,
        "drain_active": ref.drain_active,
        "drain_counter": ref.drain_counter,
        "tile_final": ref.current_tile_final,
    }


def assert_equal_cycle(cycle: int, actual: Dict[str, object], expected: Dict[str, object]) -> None:
    fields = (
        "read_en",
        "read_addr",
        "sram_data",
        "read_counter",
        "reading",
        "tile_final",
        "a_stage",
        "b_stage",
        "skew_a",
        "skew_b",
        "a_in",
        "b_in",
        "normal_valid",
        "drain_active",
        "drain_counter",
        "valid",
        "drain_done",
    )
    for field_name in fields:
        got = actual[field_name]
        exp = expected[field_name]
        assert got == exp, (
            f"cycle {cycle}: {field_name} mismatch\n"
            f"  actual   = {got}\n"
            f"  expected = {exp}"
        )


def trace_line(
    case_name: str,
    cycle: int,
    sheet_cycle: str,
    source_desc: str,
    actual: Dict[str, object],
    expected: Dict[str, object],
) -> str:
    return (
        f"{case_name} cy={cycle:03d} sheet={sheet_cycle:>3} | "
        f"RE={actual['read_en']}/{expected['read_en']} "
        f"ADDR={actual['read_addr']:03d}/{expected['read_addr']:03d} "
        f"SRAM={actual['sram_data']:02d}/{expected['sram_data']:02d}({source_desc}) "
        f"RC={actual['read_counter']:03d}/{expected['read_counter']:03d} | "
        f"A_STAGE A={fmt_a(actual['a_stage'])} E={fmt_a(expected['a_stage'])} | "
        f"B_STAGE A={fmt_b(actual['b_stage'])} E={fmt_b(expected['b_stage'])} | "
        f"SKEW_A A={fmt_skew(actual['skew_a'])} E={fmt_skew(expected['skew_a'])} | "
        f"SKEW_B A={fmt_skew(actual['skew_b'], True)} E={fmt_skew(expected['skew_b'], True)} | "
        f"A_IN A={fmt_a(actual['a_in'])} E={fmt_a(expected['a_in'])} | "
        f"B_IN A={fmt_b(actual['b_in'])} E={fmt_b(expected['b_in'])} | "
        f"NV={actual['normal_valid']}/{expected['normal_valid']} "
        f"DA={actual['drain_active']}/{expected['drain_active']} "
        f"DC={actual['drain_counter']:02d}/{expected['drain_counter']:02d} "
        f"V={actual['valid']}/{expected['valid']} "
        f"DONE={actual['drain_done']}/{expected['drain_done']}"
    )


def csv_row(
    case_name: str,
    cycle: int,
    sheet_cycle: str,
    source_desc: str,
    actual: Dict[str, object],
    expected: Dict[str, object],
) -> Dict[str, object]:
    return {
        "case": case_name,
        "rtl_cycle": cycle,
        "excel_sheet_cycle": sheet_cycle,
        "sram_source": source_desc,
        "read_en_actual": actual["read_en"],
        "read_en_expected": expected["read_en"],
        "read_addr_actual": actual["read_addr"],
        "read_addr_expected": expected["read_addr"],
        "sram_data_actual": actual["sram_data"],
        "sram_data_expected": expected["sram_data"],
        "read_counter_actual": actual["read_counter"],
        "read_counter_expected": expected["read_counter"],
        "a_stage_actual": fmt_a(actual["a_stage"]),
        "a_stage_expected": fmt_a(expected["a_stage"]),
        "b_stage_actual": fmt_b(actual["b_stage"]),
        "b_stage_expected": fmt_b(expected["b_stage"]),
        "skew_a_actual": fmt_skew(actual["skew_a"]),
        "skew_a_expected": fmt_skew(expected["skew_a"]),
        "skew_b_actual": fmt_skew(actual["skew_b"], True),
        "skew_b_expected": fmt_skew(expected["skew_b"], True),
        "a_in_actual": fmt_a(actual["a_in"]),
        "a_in_expected": fmt_a(expected["a_in"]),
        "b_in_actual": fmt_b(actual["b_in"]),
        "b_in_expected": fmt_b(expected["b_in"]),
        "normal_valid_actual": actual["normal_valid"],
        "normal_valid_expected": expected["normal_valid"],
        "drain_active_actual": actual["drain_active"],
        "drain_active_expected": expected["drain_active"],
        "drain_counter_actual": actual["drain_counter"],
        "drain_counter_expected": expected["drain_counter"],
        "valid_actual": actual["valid"],
        "valid_expected": expected["valid"],
        "drain_done_actual": actual["drain_done"],
        "drain_done_expected": expected["drain_done"],
        "all_internal_match": int(actual == expected),
    }


def sheet_cycle_label(case_name: str, rtl_cycle: int) -> str:
    if case_name == "B2B" and 261 <= rtl_cycle <= 274:
        # Workbook skipped 261, so its drain rows are numbered one higher.
        return str(rtl_cycle + 1)
    if case_name == "B2B" and rtl_cycle == 275:
        return "DONE"
    return str(rtl_cycle)


async def run_case(
    dut,
    *,
    case_name: str,
    end_cycle: int,
    starts: Dict[int, int],
    drain_levels: Dict[int, int],
    a_vectors: Sequence[Sequence[int]],
    b_vectors: Sequence[Sequence[int]],
    csv_name: str,
) -> None:
    ref = RefState()
    sram = SramLatency2(SRAM_IMAGE)
    rows: List[Dict[str, object]] = []
    valid_event = 0

    for cycle in range(end_cycle + 1):
        start = starts.get(cycle, 0)
        drain_en = drain_levels.get(cycle, 0)
        sram_value, source_desc = sram.value_for_cycle(cycle)

        dut.start.value = start
        dut.drain_en.value = drain_en
        dut.clear.value = 0
        dut.sram_data.value = sram_value

        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")

        ref.step(start=start, drain_en=drain_en, clear=0, sram_data=sram_value)
        actual = get_actual(dut)
        expected = get_expected(ref, sram_value)

        # Check every visible and internal variable on every cycle.
        assert_equal_cycle(cycle, actual, expected)

        # Check the Excel diagonal wavefront on every valid cycle.
        if actual["valid"]:
            excel_a, excel_b = expected_wavefront(a_vectors, b_vectors, valid_event)
            assert actual["a_in"] == excel_a, (
                f"{case_name} cycle {cycle}: Excel A wavefront mismatch\n"
                f"  actual   {fmt_a(actual['a_in'])}\n"
                f"  expected {fmt_a(excel_a)}"
            )
            assert actual["b_in"] == excel_b, (
                f"{case_name} cycle {cycle}: Excel B wavefront mismatch\n"
                f"  actual   {fmt_b(actual['b_in'])}\n"
                f"  expected {fmt_b(excel_b)}"
            )
            valid_event += 1

        label = sheet_cycle_label(case_name, cycle)
        line = trace_line(case_name, cycle, label, source_desc, actual, expected)
        if TRACE_ALL:
            dut._log.info(line)
        rows.append(csv_row(case_name, cycle, label, source_desc, actual, expected))

        # Capture the address that is visible in this displayed cycle.
        sram.capture_request(bool(actual["read_en"]), int(actual["read_addr"]))

    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = TRACE_DIR / csv_name
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    dut._log.info(
        f"PASS {case_name}: checked {end_cycle + 1} cycles, "
        f"{valid_event} Excel wavefronts, all staging registers, all "
        f"{SKEW_DEPTH} skew registers per side; CSV={csv_path}"
    )


# =============================================================================
# Tests
# =============================================================================
@cocotb.test()
async def test_single_tile_full_cycle_trace(dut) -> None:
    """One final tile: print and check every variable on every cycle."""
    assert hasattr(dut, "dbg_skew_a"), (
        "Compile with -DFEEDER_DEBUG; use the supplied Makefile"
    )
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    await reset_dut(dut)

    # Single tile is final from its start.
    await run_case(
        dut,
        case_name="ONE",
        end_cycle=145,
        starts={0: 1},
        drain_levels={cycle: 1 for cycle in range(146)},
        a_vectors=A_TILE_VECTORS,
        b_vectors=B_TILE_VECTORS,
        csv_name="single_tile_full_trace.csv",
    )


@cocotb.test()
async def test_two_tiles_full_cycle_trace(dut) -> None:
    """Two back-to-back tiles: preserve skew and drain only after tile 2."""
    assert hasattr(dut, "dbg_skew_a"), (
        "Compile with -DFEEDER_DEBUG; use the supplied Makefile"
    )
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    await reset_dut(dut)

    # Tile 1 starts non-final. Tile 2 starts at cycle 131 as final. The level is
    # raised at cycle 130, matching the controller/Excel boundary condition.
    drain_levels = {cycle: int(cycle >= 130) for cycle in range(277)}
    await run_case(
        dut,
        case_name="B2B",
        end_cycle=276,
        starts={0: 1, 131: 1},
        drain_levels=drain_levels,
        a_vectors=A_TILE_VECTORS + A_TILE_VECTORS,
        b_vectors=B_TILE_VECTORS + B_TILE_VECTORS,
        csv_name="two_tiles_full_trace.csv",
    )