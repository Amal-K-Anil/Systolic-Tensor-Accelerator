# Systolic-Tensor-Accelerator

A parameterizable output-stationary systolic array AI accelerator for streaming matrix multiplication, designed for the **SSCS Chipathon 2026 Track A** on the **GF180MCU** process node.

The accelerator computes C = A × B using an 8×8 grid of signed integer MAC units (INT8 by default, `DATA_WIDTH` configurable) with 21-bit accumulation. Activations and weights stream in continuously over two independent AXI4-Stream channels — there is no on-chip buffer memory and no controller; each stage self-generates its own phase transitions and hands them directly to the next. Tiled computation supports matrices larger than the native array size. `accelerator_core` is a clean, reusable IP boundary with a native three-channel AXI4-Stream interface, wrapped for the Chipathon padframe by a small protocol adapter (`host_interface`) that multiplexes the interface onto a narrow physical pin budget.

---

## Key Features

- **No-SRAM streaming dataflow** — activations and weights are consumed directly as they arrive; no on-chip buffer memory
- **No controller** — every module self-generates its own phase transition from its own inputs (`feeder`'s `drain_done` from `a_last`/`b_last`; `output_processor`'s `output_done` from its own last-result transfer) and hands it straight to the next stage
- **Output-stationary dataflow** — accumulators persist across all tile passes, cleared only after results are output
- **Parameterizable** — `ARRAY_SIZE`, `DATA_WIDTH`, `ACCUM_WIDTH` configurable at synthesis time; `SHIFT_BITS`/`SAT_MAX`/`SAT_MIN` give runtime-independent quantization control without RTL changes
- **Area-optimized Booth multiplier** — radix-2 Booth encoding with a deferred-correction-bit technique, avoiding per-partial-product negation adders
- **Clean IP boundary** — `accelerator_core` is fully self-contained and reusable in any SoC; the Chipathon pad-level protocol is entirely isolated in `host_interface`/`chip_core`
- **cocotb verification** — Python testbenches with a NumPy golden model, at the unit, integration, and full pad-level chip integration

---

## Design Parameters

| Parameter     | Default | Description                                                          |
| ------------- | ------- | ---------------------------------------------------------------------|
| `ARRAY_SIZE`  | 8       | MAC grid dimension (any power of 2)                                  |
| `DATA_WIDTH`  | 8       | Activation/weight/result bit width                                   |
| `ACCUM_WIDTH` | 21      | Accumulator width. 21-bit supports K≤32 without overflow; increase for larger K |
| `SHIFT_BITS`  | 0       | Right-shift applied before saturation (0 = pure clip)                |
| `SAT_MAX`     | `2^(DATA_WIDTH-1)-1` | Upper saturation bound (overridable for tighter quantization calibration) |
| `SAT_MIN`     | `-2^(DATA_WIDTH-1)`  | Lower saturation bound |

---

## Module Hierarchy

```text
chip_top                               ← fixed Chipathon padring template
 └── chip_core                         ← Slot A pin mapping (physical pads only)
     └── host_interface                ← protocol adapter: shared pad bus <-> AXI4-Stream
         └── accelerator_core          ← reusable IP boundary
             ├── feeder                ← dual-lane input, skew buffer, self-generated drain
             ├── systolic_array        ← 8×8 MAC grid
             │   └── mac_unit [×64]    ← signed integer MAC primitive
             │       └── booth_multiplier
             │           ├── booth_encoder
             │           └── partial_product_generator
             └── output_processor      ← result serialization, quantization, self-generated done
```

`accelerator_core` exposes a native three-channel AXI4-Stream interface (activation in, weight in, result out) and has no knowledge of physical pins at all. `host_interface`/`chip_core` exist purely to fit that interface onto the Chipathon padframe's Slot A pin budget — a different integration target (a wider AXI4-Stream SoC bus, for instance) would only need a different adapter at that same boundary, with `accelerator_core` itself unchanged.

---

## Repository Structure

```text
Systolic-Tensor-Accelerator/
 ├── src/
 │   ├── core/                          ← reusable RTL modules
 │   │   ├── booth_encoder.sv
 │   │   ├── ppdt_booth.sv              ← partial_product_generator
 │   │   ├── booth_multiplier.sv
 │   │   ├── mac_unit.sv
 │   │   ├── systolic_array.sv
 │   │   ├── feeder.sv
 │   │   ├── output_processor.sv
 │   │   └── accelerator_core.sv
 │   ├── chipathon_wrapper/             ← Chipathon padframe integration
 │   │   ├── chip_top.sv                ← fixed template, not modified
 │   │   ├── chip_core.sv               ← Slot A pin mapping
 │   │   ├── slot_defines.svh           ← includes the SLOT_A pad-count block
 │   │   └── host_interface.sv
 │   └── axi_wrapper/                   ← reserved for a future AXI4-Stream SoC
 │                                          wrapper; not yet implemented
 ├── cocotb/
 │   ├── timescale.v
 │   ├── Makefile                       ← make TOPLEVEL=<module> / make run-all
 │   ├── tb_mac_unit.py
 │   ├── tb_systolic_array.py
 │   ├── tb_feeder.py
 │   ├── tb_output_processor.py
 │   ├── tb_accelerator_core.py
 │   └── chip_top_tb.py
 ├── librelane/
 │   ├── config.yaml
 │   ├── pdn_cfg.tcl
 │   ├── chip_top.sdc
 │   └── slots/
 │       └── slot_a.yaml
 ├── ip/                                 ← chip_id / wafer.space logo macros
 ├── scripts/                            ← padring/layout utility scripts
 ├── info.yaml                           ← Chipathon submission metadata
 ├── lvs_config.json                     ← LVS source/layout configuration
 └── docs/
     ├── Architecture_Specification_Document.pdf
     └── Physical_Implementation_Analysis.pdf
```

---

## Quick Start — Simulation

### Prerequisites

```bash
# Install Icarus Verilog
sudo apt-get install iverilog   # Ubuntu/Debian
brew install icarus-verilog     # macOS

# Install cocotb and numpy
pip install cocotb numpy

# Verify
iverilog -V
cocotb-config --version
```

### Run a Testbench

```bash
cd cocotb/

# Run one module's testbench
make TOPLEVEL=mac_unit
make TOPLEVEL=systolic_array
make TOPLEVEL=feeder
make TOPLEVEL=output_processor
make TOPLEVEL=accelerator_core
make TOPLEVEL=chip_top

# Run every module's testbench, in order
make run-all

# Clean build artifacts
make clean

# Show all options
make help
```

### Using Docker (IIC-OSIC-TOOLS)

All tools are pre-installed in the [IIC-OSIC-TOOLS](https://github.com/iic-jku/iic-osic-tools) Docker container:

```bash
docker pull hpretl/iic-osic-tools
docker run -it --rm -v $(pwd):/workspace hpretl/iic-osic-tools

# Inside container
cd /workspace/cocotb
make TOPLEVEL=accelerator_core
```

---

## Host Interface Protocol

Slot A's pin budget (22 pins total) is not wide enough for `accelerator_core`'s full native interface, so `host_interface` shares a single 8-bit data bus across all three channels (activation, weight, result) and gives every control line a single, fixed direction — 17 pins total, no direction-switching logic needed anywhere except the shared data bus itself.

| Pin           | Dir         | Description                                                      |
| ------------- | ----------- | ------------------------------------------------------------------ |
| `data[7:0]`   | bidir       | Shared bus: activation/weight bytes in, result bytes out           |
| `a_valid`     | host → chip | Activation byte on `data` is valid this cycle                      |
| `a_ready`     | chip → host | Chip can accept an activation byte                                 |
| `a_last`      | host → chip | This is the true final activation byte of the stream                |
| `b_valid`     | host → chip | Weight byte on `data` is valid this cycle                          |
| `b_ready`     | chip → host | Chip can accept a weight byte                                       |
| `b_last`      | host → chip | This is the true final weight byte of the stream                    |
| `out_valid`   | chip → host | Result byte on `data` is valid this cycle                          |
| `out_ready`   | host → chip | Host can accept a result byte                                       |
| `out_last`    | chip → host | This is the true final result byte of the pass                      |

**Host-side protocol rules:**
```
1. Never assert a_valid and b_valid in the same cycle -- both share
   the one physical data bus, so at most one byte can be on the wire
   at a time.
2. Stop driving data the instant out_valid is observed high, and do
   not resume until the result phase ends -- the chip's OWN direction
   over the shared bus is derived directly from its own out_valid,
   so the host must yield the bus at exactly that point to avoid
   contention.
```

For an SoC integration with a wider pin/bus budget, `accelerator_core`'s native interface (below) can be used directly, with no sharing or direction-switching required.

---

## accelerator_core Interface

```systemverilog
module accelerator_core #(
    parameter ARRAY_SIZE  = 8,
    parameter DATA_WIDTH  = 8,
    parameter ACCUM_WIDTH = 21,
    parameter SHIFT_BITS  = 0,
    parameter signed [ACCUM_WIDTH-1:0] SAT_MAX = (1 <<< (DATA_WIDTH-1)) - 1,
    parameter signed [ACCUM_WIDTH-1:0] SAT_MIN = -(1 <<< (DATA_WIDTH-1))
)(
    input  logic                  clk,
    input  logic                  rst_n,

    input  logic [DATA_WIDTH-1:0] a_data,
    input  logic                  a_valid,
    output logic                  a_ready,
    input  logic                  a_last,

    input  logic [DATA_WIDTH-1:0] b_data,
    input  logic                  b_valid,
    output logic                  b_ready,
    input  logic                  b_last,

    output logic [DATA_WIDTH-1:0] out_data,
    output logic                  out_valid,
    input  logic                  out_ready,
    output logic                  out_last
);
```

---

## Compute Architecture

Each 8×8 pass streams one column of A and one row of B per cycle, skewed diagonally in `feeder` so that every MAC receives its correct operand pair on the correct cycle as the wavefront propagates through the array:

```text
A values enter from the left edge and flow right, one hop per cycle.
B values enter from the top edge and flow down, one hop per cycle.
Each MAC[i][j] accumulates A[i][k] × B[k][j] for all inner steps k.
Accumulators are never reset between passes -- only after the final
result of a full computation has been transferred out.
```

For matrices larger than 8×8, computation is split into tiles (K/ARRAY_SIZE passes), streamed back to back with no gap — `feeder` only drains and `output_processor` only begins serializing once the host has asserted `a_last`/`b_last` on the true final activation/weight byte of the entire stream, not after each individual tile.

---

## Feeder Operation

`feeder` has no internal buffer memory — it consumes activation/weight bytes directly as the host streams them:

```text
Per vector (one column of A, one row of B, ARRAY_SIZE bytes each):
  A bytes and B bytes may arrive in either order and independently
  stall, but a vector only completes (and the array only receives a
  new wavefront) once BOTH lanes have delivered all ARRAY_SIZE bytes.

Skew buffer: row i is delayed by i pulses relative to row 0, so that
  by the time a wavefront reaches row r / column c, it arrives
  exactly aligned with every other operand needed at that PE on the
  same cycle.
```

**Drain sequence** (self-triggered once `a_last`/`b_last` are both observed, no controller involved): once the true final vector is seen, `feeder` continues shifting zeros through the skew buffer for `2×(ARRAY_SIZE-1)` more cycles — long enough for the deepest row's final real value to finish propagating both through the skew buffer and across the array itself — then latches `drain_done`, one cycle after the last drain pulse to give the array's own registered accumulators time to settle.

---

## Output Processor Operation

`output_processor` serializes the systolic array's `ARRAY_SIZE × ARRAY_SIZE` accumulator grid one byte per cycle, row-major, once `output_en` (wired externally to `feeder`'s `drain_done`) goes high:

```text
Each result is right-shifted by SHIFT_BITS, then saturated to
  [SAT_MIN, SAT_MAX], then truncated to DATA_WIDTH bits.

output_done self-generates the instant the true final result
  transfers (out_valid && out_ready && out_last) -- this single pulse
  resets output_processor's own row/col counters AND is wired
  externally to BOTH feeder's and the MAC array's clear inputs,
  resetting the whole chip for the next computation with no
  controller coordinating the reset.
```

---

## Verification

Testbenches use **cocotb** (Python) with **NumPy** as the software golden model, at every level of the hierarchy.

| Testbench             | Module              | Key Checks                                                              |
| ---------------------- | -------------------- | -------------------------------------------------------------------------|
| `tb_mac_unit`          | `mac_unit`           | Signed multiply, accumulation, clear, valid-gated A/B propagation       |
| `tb_systolic_array`    | `systolic_array`     | Matrix multiply vs NumPy, PE-to-PE wiring (token-trace), skew timing     |
| `tb_feeder`            | `feeder`             | Stalls, lane imbalance, drain sequencing, reset/clear, back-to-back runs|
| `tb_output_processor`  | `output_processor`   | Saturation/quantization, backpressure, `output_done` timing, edge cases  |
| `tb_accelerator_core`  | `accelerator_core`   | Single/multi-pass matmul vs NumPy, saturation, backpressure, input stalls|
| `chip_top_tb`          | `chip_top` (Slot A)  | One full matrix multiply through the real physical pad interface         |

---

## Physical Design

Physical implementation targets **Slot A** — one of four possible corner positions in the shared Chipathon padframe. Slot A's total pin budget is 22, and this design uses all 22: 5 input-only + 12 bidirectional + 1 analog workaround pin + 2 clock/reset + 2 power (1 DVDD + 1 DVSS). Implemented via the **LibreLane** RTL-to-GDS flow against the **`gf180mcu_fd_sc_mcu7t5v0`** (7-track, 5V) standard cell library.

```bash
# From the repo root
make clone-pdk                 # one-time PDK setup
make librelane-padring SLOT=a  # validate padring/pin fit only
make librelane SLOT=a          # full synthesis -> PnR -> GDS
make render-image               # render a PNG of the final GDS
```

Environment options:
- **Nix flake**: `nix develop` (uses `flake.nix` at repo root)
- **Docker**: IIC-OSIC-TOOLS container (all tools pre-installed)

---

## Team

**Team Maxilerator — SSCS Chipathon 2026 Track A**

| Name                       | GitHub           | Affiliation                                           | Role        |
| --------------------------- | ----------------- | -------------------------------------------------------- | ------------- |
| Irene Raphael              | @Irene-ux        | Technical University of Munich                        | Team Lead   |
| Amal Kunnath Anil Narayana | @Amal-K-Anil     | Technical University of Munich                        | Team Member |
| Muhammed Rabin K C         | @muhammedrabinkc | Technical University of Munich                        | Team Member |
| Muhammad Faqih Ilmi        | @mfaqih222ilmi   | National Taiwan University of Science and Technology  | Team Member |
| Akhil S Nair               | @akhilJyothi     | Indian Institute of Technology, Delhi                 | Team Member |

---

## Documentation

- [Architecture Specification](docs/Architecture_Specification_Document_v1.0.pdf)
- [Physical Implementation Analysis](docs/Physical_Implementation_Analysis_v1.0.pdf)
- [Project Proposal](docs/Chipathon_Proposal_Slides_v1.0.pdf)
- [Schematic Review Slides](docs/Schematic_Review_Slides_v1.1.pdf)
- [Progress Tracker](https://docs.google.com/spreadsheets/d/1Rfl_xbEPnYtsQbiFe8S4vHPcbO-48h-Qb6fZFTNUoBU/edit?usp=sharing)
- [Chipathon 2026 Issue #60](https://github.com/sscs-ose/sscs-chipathon-2026/issues/60)

---

## License

Apache 2.0 — see [LICENSE](LICENSE)
