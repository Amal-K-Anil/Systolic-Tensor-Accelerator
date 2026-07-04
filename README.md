# Systolic-Tensor-Accelerator

A parameterizable output-stationary INT8 systolic array AI accelerator for tiled matrix multiplication, designed for the **SSCS Chipathon 2026 Track A** on the **GF180MCU** process node.

The accelerator computes C = A × B using an 8×8 grid of signed INT8 MAC units with 21-bit accumulation. Tiled computation supports matrices larger than the native array size. The design is modular and reusable — `accelerator_core` exposes a clean byte-wide interface compatible with both the Chipathon physical host interface and an optional AXI4-Stream SoC wrapper.

---

## Key Features

- **Output-stationary dataflow** — accumulators persist across all tile passes, cleared only after results are output
- **Parameterizable** — `ARRAY_SIZE` and `ACCUM_WIDTH` configurable at synthesis time without RTL changes
- **Ping-pong SRAM buffering** — simultaneous host loading and feeder compute with zero overhead
- **GF180MCU SRAM macros** — uses `gf180mcu_fd_ip_sram__sram128x8m8wm1` hard macros
- **Clean IP boundary** — `accelerator_core` reusable in any SoC via AXI4-Stream wrapper
- **cocotb verification** — Python testbenches with NumPy golden model

---

## Design Parameters

| Parameter     | Default | Description                                              |
| ------------- | ------- | -------------------------------------------------------- |
| `ARRAY_SIZE`  | 8       | MAC grid dimension (supports 2, 4, 8)                    |
| `ACCUM_WIDTH` | 21      | Accumulator width. 21-bit supports K≤32; increase for larger K |

---

## Module Hierarchy

```text
accelerator_top                        ← Chipathon tapeout submission
 ├── host_interface                    ← Physical pad protocol, bidir OE
 └── accelerator_core                  ← Reusable IP boundary
     ├── memory                        ← Two GF180MCU SRAM macros, ping-pong
     ├── feeder                        ← Pipelined reads, skew buffer, drain phase
     ├── controller                    ← 3-state FSM (IDLE, PROCESSING, OUTPUT)
     ├── systolic_array                ← 8×8 MAC grid
     │   └── mac_unit [×64]            ← Signed INT8 MAC primitive
     └── output_processor              ← Result serialization, INT8 saturation

accelerator_axi_wrapper                ← SoC reference wrapper (simulation only)
 ├── axi4_stream_slave                 ← AXI slave → internal signals
 ├── axi4_stream_master                ← internal signals → AXI master
 └── accelerator_core
```

---

## Repository Structure

```text
Systolic-Tensor-Accelerator/
 ├── src/
 │   ├── core/                         ← reusable RTL modules
 │   │   ├── mac_unit.sv
 │   │   ├── systolic_array.sv
 │   │   ├── feeder.sv
 │   │   ├── memory.sv
 │   │   ├── controller.sv
 │   │   ├── output_processor.sv
 │   │   └── accelerator_core.sv
 │   ├── chipathon_wrapper/            ← Chipathon tapeout files
 │   │   ├── chip_top.sv
 │   │   ├── chip_core.sv
 │   │   ├── slot_defines.svh
 │   │   ├── host_interface.sv
 │   │   └── accelerator_top.sv
 │   └── axi_wrapper/                  ← SoC reference wrapper
 │       ├── axi4_stream_slave.sv
 │       ├── axi4_stream_master.sv
 │       └── accelerator_axi_wrapper.sv
 ├── cocotb/
 │   ├── timescale.v
 │   ├── Makefile                      ← shared: make TOPLEVEL=<module>
 │   ├── tb_mac_unit.py
 │   ├── tb_systolic_array.py
 │   ├── tb_feeder.py
 │   ├── tb_memory.py
 │   ├── tb_controller.py
 │   ├── tb_output_processor.py
 │   ├── tb_accelerator_core.py
 │   ├── tb_accelerator_top.py
 │   ├── tb_axi_wrapper.py
 │   └── chip_top_tb.py
 ├── librelane/
 │   ├── config.yaml
 │   ├── pdn_cfg.tcl
 │   ├── chip_top.sdc
 │   └── slots/
 │       └── slot_workshop.yaml
 ├── scripts/
 │   ├── golden_model.py
 │   └── run_regression.py
 └── docs/
     ├── architecture_spec.md
     └── physical_implementation_analysis.md
```

---

## Quick Start — Simulation

### Prerequisites

```bash
# Install Icarus Verilog
sudo apt-get install iverilog   # Ubuntu/Debian
brew install icarus-verilog     # macOS

# Install cocotb
pip install cocotb

# Verify
iverilog -V
cocotb-config --version
```

### Run a Testbench

```bash
cd cocotb/

# Run specific module testbench
make TOPLEVEL=mac_unit
make TOPLEVEL=controller
make TOPLEVEL=feeder
make TOPLEVEL=systolic_array
make TOPLEVEL=accelerator_core

# Run all unit testbenches
make all

# Run all integration testbenches
make all-integration

# Clean build artifacts
make clean

# Show all options
make help
```

### Using Docker (IIC-OSIC-TOOLS)

All tools are pre-installed in the [IIC-OSIC-TOOLS](https://github.com/iic-jku/iic-osic-tools) Docker container — no manual installation needed:

```bash
# Pull and run container
docker pull hpretl/iic-osic-tools
docker run -it --rm -v $(pwd):/workspace hpretl/iic-osic-tools

# Inside container
cd /workspace/cocotb
make TOPLEVEL=controller
```

---

## Host Interface Protocol

The physical chip exposes a simple byte-wide interface for bring-up via laptop/FTDI/microcontroller:

| Pin              | Dir    | Description                                                        |
| ---------------- | ------ | ------------------------------------------------------------------ |
| `clk`            | in     | System clock (25 MHz)                                              |
| `rst_n`          | in     | Active-low reset                                                   |
| `pad_data[7:0]`  | bidir  | Tile input bytes in / result bytes out                             |
| `pad_valid_in`   | in     | Host holds HIGH while sending tile bytes                           |
| `pad_ready_in`   | out    | Permission pulse: HIGH until first byte of new tile received       |
| `pad_tile_done`  | in     | Single-cycle pulse: all 128 bytes of tile transferred              |
| `pad_last_pass`  | in     | Level: HIGH before/during final tile pass                          |
| `pad_valid_out`  | out    | HIGH while chip sends result bytes                                 |
| `pad_ready_out`  | in     | Host holds HIGH when ready to receive result bytes                 |

**Transfer rules:**
```
Tile permission : pad_ready_in = 1         → host may send next tile
Byte write      : pad_valid_in = 1         → one byte written to SRAM
Output transfer : pad_valid_out = 1
              AND pad_ready_out = 1         → one result byte transferred
```

---

## accelerator_core Interface

```systemverilog
module accelerator_core #(
    parameter ARRAY_SIZE  = 8,
    parameter ACCUM_WIDTH = 21
)(
    input  logic        clk, rst_n,
    input  logic [7:0]  data_in,
    input  logic        valid_in,
    output logic        ready_in,
    input  logic        tile_done,
    input  logic        last_pass,
    output logic [7:0]  data_out,
    output logic        valid_out,
    input  logic        ready_out
);
```

---

## Physical Design

Physical implementation targets **Slot A** (~1,248,806 µm²) of the Chipathon 2026 padframe using the **LibreLane** RTL-to-GDS flow.

```bash
# Run LibreLane (from repo root, inside IIC-OSIC-TOOLS or Nix shell)
cd librelane/
librelane config.yaml
```

Environment options:
- **Nix flake**: `nix develop` (uses `flake.nix` at repo root)
- **Docker**: IIC-OSIC-TOOLS container (all tools pre-installed)

**Area estimates at 70% utilization:**

| Component         | Cell Area (µm²) | Placed Area (µm²) |
| ----------------- | --------------- | ----------------- |
| 64 MAC units      | 566,045         | 808,636           |
| SRAM_0 (fixed)    | 116,119         | 116,119           |
| SRAM_1 (fixed)    | 116,119         | 116,119           |
| output_processor  | 32,250          | 46,071            |
| Feeder            | 37,843          | 54,062            |
| Controller        | 1,267           | 1,810             |
| host_interface    | 632             | 903               |
| **Total**         | **870,275**     | **1,143,718**     |
| **Slot A %**      |                 | **91.6%** ✅      |

---

## Verification

Testbenches use **cocotb** (Python) with **NumPy** as the software golden model.

| Testbench               | Module              | Key Checks                                              |
| ----------------------- | ------------------- | ------------------------------------------------------- |
| `tb_mac_unit`           | `mac_unit`          | Signed multiply, accumulation, clear, valid-gated A/B   |
| `tb_systolic_array`     | `systolic_array`    | 8×8 matrix multiply vs NumPy, skew pattern              |
| `tb_feeder`             | `feeder`            | Pipelined reads, skew buffer, 14-cycle drain            |
| `tb_memory`             | `memory`            | Ping-pong swap, CEN/GWEN active-low                     |
| `tb_controller`         | `controller`        | FSM transitions, swap timing, drain_en latch            |
| `tb_output_processor`   | `output_processor`  | INT8 saturation, serialization, backpressure            |
| `tb_accelerator_core`   | `accelerator_core`  | End-to-end 8×8, 16×16, 32×32 vs NumPy                  |

---

## Team

**Team Maxilerator — SSCS Chipathon 2026 Track A**

| Name                       | GitHub           | Affiliation                                           | Role        |
| -------------------------- | ---------------- | ----------------------------------------------------- | ----------- |
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
- [Chipathon 2026 Issue #60](https://github.com/sscs-ose/sscs-chipathon-2026/issues/60)

---

## License

Apache 2.0 — see [LICENSE](LICENSE)
