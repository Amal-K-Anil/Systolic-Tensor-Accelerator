# Project Status / Continuation Guide

This document is the main handover for the Systolic Tensor Accelerator project.

If development is resumed in the future, start here.

The recommended continuation branch is:

`latest-dev`

This branch contains the latest useful RTL, verification, physical-design configuration, required synthesis override, and historical reference material needed to understand the previous timing and integration work.

---

# 1. Recommended Branch

## `latest-dev`

Use `latest-dev` for all future continuation work.

It contains:

- latest optimized accelerator RTL
- latest cocotb tests
- padless chip-level wrapper
- updated SDC constraints
- ACE2 physical-design configuration
- current reviewed `info.yaml`
- active LibreLane/Yosys synthesis override
- historical ACE2 integration reference
- historical timing-repair experiments
- continuation documentation

The project has intentionally been consolidated so that a future developer does not need another experimental branch to recover important timing work.

Historical timing material is stored under:

`reference/timing-repair/`

and is clearly separated from the active flow.

---

# 2. Repository Organization

The important top-level structure is:

```text
Systolic-Tensor-Accelerator/
│
├── src/
│   ├── core/
│   └── chipathon_wrapper/
│
├── cocotb/
│
├── librelane/
│   ├── config.yaml
│   ├── chip_top.sdc
│   └── slots/
│       └── slot_ace2.yaml
│
├── tools/
│   └── librelane_override/
│       └── librelane/
│
├── reference/
│   ├── README.md
│   ├── info_ace2_last_tested.yaml
│   └── timing-repair/
│       ├── README.md
│       ├── historical timing configs
│       ├── custom OpenROAD/LibreLane experiments
│       └── output_processor_positive_slack_reference.sv
│
├── info.yaml
├── Makefile
└── PROJECT_STATUS.md
```

---

# 3. Active vs Historical Material

This distinction is important.

## Active project files

The following are part of the current development state:

- `src/`
- `cocotb/`
- `librelane/`
- `info.yaml`
- `Makefile`
- `tools/librelane_override/`

These are the files to use when continuing development.

## Historical/reference material

Everything under:

`reference/`

exists for comparison, previous implementation context, or possible reuse of older ideas.

Do not copy reference material back into the active design automatically.

Read:

`reference/README.md`

before using anything from that directory.

---

# 4. Accelerator Architecture

The design is a parameterizable output-stationary systolic-array accelerator intended for streaming matrix multiplication / CNN-style computation.

The main active core files are:

- `src/core/accelerator_core.sv`
- `src/core/feeder.sv`
- `src/core/mac_unit.sv`
- `src/core/output_processor.sv`
- `src/core/systolic_array.sv`

The later development work focused heavily on reducing large control-net fanout and improving physical timing behavior.

---

# 5. High-Fanout RTL Optimizations

A major physical-design problem was high fanout on global control signals.

The RTL was changed so that control distribution is replicated locally instead of relying on a few very high-fanout registers.

Important examples include:

- replicated feeder valid state
- replicated skew-valid state
- replicated MAC clear state
- replicated local column state in the output processor

The relevant registers use:

```systemverilog
(* keep = "true" *)
```

where required.

These replications are intentional and should not be simplified away without understanding the physical-design consequences.

---

# 6. Feeder Changes

The feeder was modified to reduce fanout through replicated control state.

Important replicated structures include approximately:

- 64 local valid registers
- 7 skew-valid registers

These registers were intentionally distributed so that synthesis and implementation would not create one large control tree feeding the full array.

---

# 7. Output Processor Changes

The output processor went through several timing-oriented architectural iterations.

The active implementation contains:

- replicated local column counters
- replicated clear generation
- global pipeline advance/stall behavior
- registered completion behavior
- output backpressure handling
- row-major result serialization
- shift / saturation / truncation logic

The current `output_done` behavior is important:

`output_done` is registered and fires one cycle after the accepted final result transfer.

The actual final transfer is detected from:

```text
out_valid && out_ready && out_last
```

The final transfer resets serialization state and registers the one-cycle `output_done` pulse.

The cocotb tests were updated to match this behavior.

---

# 8. MAC Clear Behavior

The MAC-unit clear behavior was also updated during optimization.

The current verification expects `clear` to reset the accumulation state.

The cocotb tests no longer require `a_out` and `b_out` to be cleared together with the accumulator.

See:

`cocotb/tb_mac_unit.py`

for the current expected behavior.

---

# 9. Verification State

The latest cocotb test updates are included in `latest-dev`.

Important updated tests include:

- MAC clear behavior
- registered `output_done`
- final-transfer timing
- output-ready stall behavior
- counter reset timing
- cleanup-cycle behavior between serialization sessions

Relevant files:

- `cocotb/tb_mac_unit.py`
- `cocotb/tb_output_processor.py`

These test changes were preserved together with the final RTL because they document the intended behavior of the optimized design.

---

# 10. Top-Level Integration

The latest top-level wrapper is **padless**.

The project no longer directly instantiates the GF180 physical I/O pad cells inside `chip_top.sv`.

The active wrapper is:

`src/chipathon_wrapper/chip_top.sv`

The external logical interface contains:

- `clk`
- `rst_n`
- `data[7:0]`
- `a_valid_i`
- `a_last_i`
- `a_ready_o`
- `b_valid_i`
- `b_last_i`
- `b_ready_o`
- `out_valid_o`
- `out_last_o`
- `out_ready_i`

The physical padframe is expected to be handled by the chip-level integration process.

This replaced the earlier wrapper style in which physical GF180 I/O cells were instantiated directly.

---

# 11. Slot Definition

The active wrapper uses:

`SLOT_ACE2`

through:

`src/chipathon_wrapper/slot_defines.svh`

The older `SLOT_A` physical-pad-style integration was replaced during the later ACE2 work.

---

# 12. Current `info.yaml`

The repository-root:

`info.yaml`

is the newer reviewed organizer/reviewer version.

It contains the later pad assignment including:

- explicit VDD
- explicit VSS
- explicit unused / NC positions
- WEST-side allocation
- NORTH-side allocation
- shared `data[7:0]`
- A-stream control signals
- B-stream control signals
- output-stream control signals

Unused pad positions are represented explicitly as analog NC locations where required.

This root file is the current integration definition and should remain authoritative unless the organizer provides a newer specification.

---

# 13. Important `info.yaml` / ACE2 Caveat

The newer root `info.yaml` was introduced **after** the last locally exercised ACE2 physical-design runs.

Therefore the following two things should not be assumed to have already been validated together:

1. the current root `info.yaml`
2. the old ACE2 physical implementation and timing results

The earlier ACE2-era `info.yaml` has been preserved as:

`reference/info_ace2_last_tested.yaml`

That file exists only to show what was present during the last ACE2 implementation work.

Do not replace the root `info.yaml` with it.

A future continuation should reconcile the final organizer padframe / slot DEF with the current root `info.yaml` before signoff.

---

# 14. ACE2 Floorplan

The last locally exercised floorplan is:

`librelane/slots/slot_ace2.yaml`

It was an experimental ACE2 configuration created before the final organizer physical integration data was available.

Important properties include:

```text
DIE_AREA = 2235 × 2235 µm
```

The experimental slot represented approximately a 7/8-size usable block.

Two unavailable corner regions were modeled using placement, routing, and PDN obstructions.

The unavailable regions were approximately:

```text
lower-left:
0,0 to 560,560
```

and:

```text
upper-right:
1675,1675 to 2235,2235
```

Corresponding temporary pin exclusions were also used.

This floorplan should be treated as the last tested local physical approximation, not as guaranteed final organizer geometry.

---

# 15. Current Physical-Design Flow

The later development moved to the LibreLane:

`Classic`

flow.

Important active configuration choices include:

```text
SYNTH_STRATEGY: DELAY 4
```

placement density around:

```text
50%
```

and:

```text
PL_OPTIMIZE_MIRRORING: true
CTS_APPLY_NDR: none
GRT_ALLOW_CONGESTION: false
RUN_POST_GRT_RESIZER_TIMING: true
```

The flow also uses:

```text
MAX_TRANSITION_CONSTRAINT: 4
```

while the explicit max-capacitance constraint was disabled in the later configuration.

---

# 16. Delay-Cell Exclusion

One of the most important timing discoveries was that OpenROAD repair stages could insert large numbers of GF180 delay cells.

The relevant families included:

```text
gf180mcu_fd_sc_mcu7t5v0__dlya_*
gf180mcu_fd_sc_mcu7t5v0__dlyb_*
gf180mcu_fd_sc_mcu7t5v0__dlyc_*
gf180mcu_fd_sc_mcu7t5v0__dlyd_*
```

These insertions badly degraded setup timing.

The later configuration excludes all of these delay-cell families.

This change produced a major improvement in setup timing and should not be removed casually.

---

# 17. Clock Constraint

The design was targeting:

```text
Clock period: 40 ns
Frequency:    25 MHz
```

The active SDC is:

`librelane/chip_top.sdc`

It was updated for the padless top-level interface.

The clock is applied directly to:

`clk`

instead of the older physical pad path.

Input/output delays are defined for the shared data bus and stream-control interface.

---

# 18. Required LibreLane/Yosys Override

This is a critical part of the latest development environment.

The optimized RTL intentionally replicates control registers and marks them using:

```systemverilog
(* keep = "true" *)
```

However, Yosys originally merged some of these equivalent replicated registers during synthesis.

That recreated the high-fanout problem even though the RTL had been explicitly replicated.

A project-local LibreLane override is therefore preserved under:

`tools/librelane_override/`

The important modified file is:

`tools/librelane_override/librelane/scripts/pyosys/synthesize.py`

Relative to the stock installed LibreLane version, the important intentional addition is:

```python
d.run_pass("proc_dff")

# Preserve intentionally replicated control registers.
d.run_pass("attrmvcp", "-copy", "-attr", "keep")

d.run_pass("proc_memwr")
```

The `attrmvcp` pass propagates the `keep` attribute so that the intended replicated control structure survives synthesis.

---

# 19. How to Activate the LibreLane Override

Before running the preserved flow, use:

```sh
export PYTHONPATH="$PWD/tools/librelane_override${PYTHONPATH:+:$PYTHONPATH}"
```

Then LibreLane can be launched using the project-local package override.

The run style used during the latest physical-design work was approximately:

```sh
export PYTHONPATH="$PWD/tools/librelane_override${PYTHONPATH:+:$PYTHONPATH}"

python3 -m librelane \
  librelane/slots/slot_ace2.yaml \
  librelane/config.yaml \
  --save-views-to "$PWD/final" \
  --pdk gf180mcuD \
  --pdk-root /foss/pdks \
  --manual-pdk
```

The exact PDK paths may need adjustment in a new environment.

---

# 20. Makefile Caveat

The Makefile contains convenience targets, including ACE2 selection.

The later configuration used ACE2 as the default slot.

However, the Makefile historically did **not** automatically add the project-local LibreLane override to `PYTHONPATH`.

Therefore do not assume that:

```sh
make librelane
```

automatically uses:

`tools/librelane_override/`

unless the Makefile is explicitly updated to do so.

Always verify the Python import path before synthesis.

---

# 21. Legacy Padring Target

The Makefile also contains an older pad-ring-related target using the previous integration approach.

That target belongs to the older physical-pad workflow.

The later project direction moved toward a padless logical wrapper with the physical padframe generated or integrated externally.

Treat the older padring target as legacy unless the organizer's final integration flow specifically requires it.

---

# 22. Timing-Closure History

The physical-design effort progressed through several timing problems.

Important issues included:

- high-fanout valid distribution
- high-fanout clear distribution
- synthesized merging of replicated registers
- clock-tree NDR behavior
- delay-cell insertion
- setup timing
- hold timing
- slew violations
- fanout violations
- capacitance violations

Several of these were substantially improved.

---

# 23. High-Fanout Synthesis Fix

After adding replicated RTL registers, synthesis initially collapsed equivalent registers back together.

The `attrmvcp` synthesis modification described earlier fixed this.

After the fix, the replicated registers could be observed as separate synthesized flip-flop Q pins instead of one merged high-fanout source.

This was a prerequisite for the later timing improvements.

---

# 24. CTS NDR Finding

Clock-tree synthesis was also affected by NDR-related behavior.

The later stable direction used:

```text
CTS_APPLY_NDR: none
```

This setting should remain the baseline unless new timing or routing evidence justifies changing it.

---

# 25. Best Synthesis / Placement Direction

Among the tested strategies, the best later direction used:

```text
SYNTH_STRATEGY: DELAY 4
```

with approximately:

```text
placement density: 50%
```

This became the preferred baseline after comparisons with other synthesis/placement settings.

---

# 26. Last Fully Completed Useful Timing Run

The most important completed later run used:

```text
GRT_RESIZER_HOLD_SLACK_MARGIN: 2.5
```

The run directory was:

```text
RUN_2026-08-22_14-01-02
```

Final timing results were approximately:

| Corner | Hold slack | Setup slack |
|---|---:|---:|
| `nom_tt` | +0.186874 ns | +16.346313 ns |
| `nom_ss` | +0.628320 ns | +3.145679 ns |
| `nom_ff` | -0.021312 ns | +21.448765 ns |
| `max_tt` | +0.174178 ns | +14.977202 ns |
| `max_ss` | +0.625199 ns | +2.310532 ns |
| `max_ff` | -0.037662 ns | +20.536133 ns |

This means setup timing was positive in all listed analyzed corners.

The remaining hold issue was very small in the fast corners.

The worst remaining hold slack was approximately:

```text
-0.038 ns
```

or about:

```text
38 ps
```

---

# 27. Remaining Hold Violator

At the end of the best completed run, the remaining fast-corner hold problem was essentially associated with one short input path.

The observed endpoint was approximately:

```text
data[6] -> _83701_/D
```

This should be re-evaluated after any floorplan, padframe, constraint, or routing changes because synthesized instance names may change.

Do not hard-code future repair logic around `_83701_`.

---

# 28. Electrical Violations Were Not Fully Closed

Although setup timing improved substantially, the design was **not signoff-clean**.

The slow corner still contained many electrical violations.

In the best later run, the `max_ss` corner had approximately:

```text
~1422 slew violations
~207 fanout violations
~13 capacitance violations
```

These values should be treated as historical context rather than guaranteed results for a future rerun.

A future implementation may produce different counts after changes to:

- padframe
- floorplan
- placement
- routing
- constraints
- OpenROAD/LibreLane version
- PDK version

---

# 29. Current 2.6 Hold-Margin Setting

After the successful 2.5-margin run, the configuration was changed to:

```text
GRT_RESIZER_HOLD_SLACK_MARGIN: 2.6
```

This is the value currently preserved in the active configuration.

However, it has **not been validated by a completed timing run**.

The attempted run was:

```text
RUN_2026-08-22_16-00-18
```

and failed much earlier in the flow while OpenROAD was writing an ODB file.

The reported failure was an I/O error similar to:

```text
OSError: [Errno 5] Input/output error
```

The run failed around the Cut Rows / ODB-write stage, before the timing-repair stages relevant to comparing 2.5 against 2.6.

Therefore:

```text
2.5 = last completed/validated hold-margin experiment
2.6 = current configuration, but unvalidated
```

Do not claim that 2.6 is better until it is successfully rerun.

---

# 30. Disk-Space Context of the Failed Run

At the time of the ODB I/O failure, the filesystem was checked and there was still substantial free storage.

The failure therefore did not appear to be a simple normal out-of-disk-space condition.

If the issue occurs again, investigate:

- filesystem health
- container/storage backend
- host I/O
- mounted volume behavior
- OpenROAD database-write failure

rather than assuming timing configuration caused the failure.

---

# 31. Historical Timing-Repair Experiments

Earlier repo5 work explored more aggressive custom timing repair.

Those useful experiments have been consolidated under:

`reference/timing-repair/`

They include:

- second post-GRT design-repair pass
- stronger post-GRT slew repair
- modified DRT antenna rerouting
- extracted-RC post-route slew feedback
- ECO patch generation
- ECO replay
- repeated routing and RC extraction
- residual non-core repair
- an older positive-slack output-processor architecture

These experiments are **reference material only**.

They are not enabled in the active flow.

Read:

`reference/timing-repair/README.md`

before attempting to reuse them.

---

# 32. Alternative Positive-Slack Output Processor

The file:

`reference/timing-repair/output_processor_positive_slack_reference.sv`

contains an older output-processor architecture that was saved during a positive-slack timing experiment.

It uses a materially different three-stage serialization pipeline.

It is preserved because it may be useful if output serialization becomes timing-critical again.

It is **not** the current RTL.

The active file remains:

`src/core/output_processor.sv`

Do not substitute the reference version without complete re-verification.

---

# 33. Reference Directory

The complete historical-reference area is:

`reference/`

Its contents currently include:

## `reference/README.md`

Explains the purpose of the reference directory and the difference between active and historical material.

## `reference/info_ace2_last_tested.yaml`

Preserves the older ACE2-era integration definition used during the last locally exercised ACE2 work.

## `reference/timing-repair/`

Preserves the useful earlier timing-repair experiments and alternative timing architecture.

The `reference/` directory should remain separate from the active implementation.

---

# 34. Active Tool Override

Unlike `reference/`, the directory:

`tools/librelane_override/`

is active infrastructure.

It exists because the current optimized RTL relies on synthesis preserving intentionally replicated control registers.

Do not classify this directory as historical reference material.

If the synthesis override is eventually removed, first confirm that the stock LibreLane/Yosys version being used already preserves the required `keep` semantics correctly.

---

# 35. Final Physical Integration Is Still Open

The project has not yet completed final physical integration against the final organizer geometry/padframe.

The last locally exercised implementation used the experimental ACE2 floorplan.

The newer reviewed root `info.yaml` reflects a later integration definition.

A future continuation must reconcile:

- final organizer slot geometry
- final DEF / floorplan
- final pad locations
- power/ground requirements
- current `info.yaml`
- padless top-level wrapper
- SDC constraints
- PDN strategy

before considering the layout final.

---

# 36. PDN Direction

The later ACE2 work moved away from the earlier pad-connected core-ring style.

The later configuration used a more boundary-oriented PDN setup with settings including:

```text
FP_PDN_CORE_RING: false
FP_PDN_ENABLE_RAILS: true
PDN_CONNECT_TO_PADS: false
PDN_ENABLE_PINS: true
PDN_EXTEND_TO: boundary
```

The exact values should be checked in the active `librelane/config.yaml`.

If final organizer integration provides explicit power-pad or ring requirements, the PDN configuration may need to be revised.

---

# 37. Signoff Status

The project should **not** be considered final/signoff-complete.

The later development had made strong progress in timing, but remaining work included:

- remaining hold cleanup
- slew cleanup
- fanout cleanup
- capacitance cleanup
- final floorplan reconciliation
- final padframe integration
- final PDN validation
- final DRC
- final LVS
- final timing signoff on the final geometry

An earlier project phase had produced successful routing and LVS results on an older physical configuration, but those results should not be interpreted as signoff for the later ACE2/current integration state.

---

# 38. Recommended Resume Procedure

If development is resumed, follow this order.

## Step 1 — Checkout the continuation branch

```sh
git checkout latest-dev
```

or:

```sh
git switch latest-dev
```

---

## Step 2 — Read the documentation

Read:

```text
PROJECT_STATUS.md
reference/README.md
reference/timing-repair/README.md
```

before modifying the flow.

---

## Step 3 — Confirm the environment

Verify:

- LibreLane version
- OpenROAD version
- Yosys version
- GF180 PDK installation
- Python version
- PDK root path

The preserved override was developed against the environment available during the 2026 work.

Version changes may alter synthesis or physical-design behavior.

---

## Step 4 — Activate the synthesis override

From the repository root:

```sh
export PYTHONPATH="$PWD/tools/librelane_override${PYTHONPATH:+:$PYTHONPATH}"
```

Confirm that Python is loading LibreLane from the project-local override before trusting synthesis results.

---

## Step 5 — Review final organizer integration data

Before spending time on timing closure, obtain or confirm the final:

- slot geometry
- slot DEF
- pad locations
- pad types
- power/ground positions
- physical obstructions
- organizer integration requirements

Then compare those against:

```text
info.yaml
librelane/slots/slot_ace2.yaml
src/chipathon_wrapper/chip_top.sv
librelane/chip_top.sdc
```

---

## Step 6 — Reconcile the current `info.yaml`

Use the repository-root `info.yaml` as the current logical integration definition.

Use:

`reference/info_ace2_last_tested.yaml`

only to understand the older ACE2 context.

Do not silently revert to the historical file.

---

## Step 7 — Reproduce synthesis

Run synthesis with the local LibreLane override enabled.

Verify that replicated `(* keep *)` registers remain separate after synthesis.

In particular, check the feeder valid distribution and output-processor clear distribution.

If equivalent registers have been merged again, stop before physical design and investigate the synthesis environment.

---

## Step 8 — Reproduce physical implementation

Use the active:

```text
librelane/config.yaml
librelane/chip_top.sdc
```

with the appropriate final slot configuration.

If the final organizer floorplan differs from ACE2, update the slot configuration before interpreting timing comparisons.

---

## Step 9 — Establish a new baseline

Before applying historical repair experiments, record:

- setup slack by corner
- hold slack by corner
- slew violations
- fanout violations
- capacitance violations
- congestion
- routing status
- DRC status
- LVS status

This becomes the new continuation baseline.

---

## Step 10 — Compare against the historical best

The main historical timing target to compare against is the completed 2.5-margin run.

Important reference values:

```text
max_ss setup ≈ +2.31 ns
max_ss hold  ≈ +0.625 ns
max_ff setup ≈ +20.54 ns
max_ff hold  ≈ -0.038 ns
```

Do not expect exact reproduction if the floorplan, padframe, tools, or PDK have changed.

---

## Step 11 — Resolve remaining hold

Re-evaluate the remaining fast-corner input hold paths.

Avoid instance-name-specific fixes because synthesized instance names can change.

Prefer structural or constraint-aware repair.

---

## Step 12 — Continue electrical cleanup

Focus on:

- slew
- fanout
- capacitance

while monitoring setup and hold so that electrical repair does not recreate the earlier timing degradation.

Keep the delay-cell exclusions unless there is strong evidence that re-enabling a specific family improves overall closure.

---

## Step 13 — Consult historical timing experiments only if necessary

If the normal active flow cannot close remaining electrical issues, inspect:

`reference/timing-repair/`

Possible ideas include:

- second post-GRT repair
- extracted-RC feedback
- ECO replay
- alternative output serialization architecture

Reintroduce these individually and measure their impact.

Do not enable all historical modifications at once.

---

## Step 14 — Final signoff

Once the final physical integration is stable, rerun:

- all timing corners
- DRC
- LVS
- antenna checks
- power/IR checks
- final routing checks

Only results generated from the final organizer-compatible physical design should be treated as final signoff evidence.

---

# 39. Key Things Not to Forget

The most important continuation points are:

1. Continue from `latest-dev`.
2. The root `info.yaml` is newer than the last ACE2 physical run.
3. `reference/info_ace2_last_tested.yaml` is historical only.
4. The top-level wrapper is padless.
5. The active synthesis override lives under `tools/librelane_override/`.
6. Activate that override through `PYTHONPATH`.
7. The override preserves replicated `(* keep *)` control registers.
8. Delay-cell exclusion was important for setup timing.
9. `DELAY 4` with density around 50% was the strongest later direction.
10. The 2.5 hold-margin run is the last fully completed timing reference.
11. The current 2.6 setting is not validated.
12. Setup was closed in the best later run.
13. A very small fast-corner hold violation remained.
14. Electrical violations were still significant.
15. The final organizer padframe/floorplan still needs reconciliation.
16. `reference/timing-repair/` contains useful historical experiments but is not active flow.
17. The project is not yet final signoff-clean.

---

# 40. Current Overall Status

The project had progressed beyond basic RTL development.

The main remaining challenge was no longer functional design, but physical integration and timing/electrical closure.

Major accomplishments already incorporated into `latest-dev` include:

- developed systolic accelerator RTL
- functional verification updates
- high-fanout RTL restructuring
- synthesis preservation of replicated control logic
- padless chip wrapper
- ACE2 physical-design configuration
- improved synthesis/placement direction
- elimination of problematic delay-cell insertion
- positive setup timing across the analyzed corners
- near-closure of hold timing
- preservation of useful historical repair experiments

The recommended continuation strategy is therefore:

**preserve the current RTL architecture, establish the final organizer-compatible physical implementation, reproduce the later timing baseline, and continue physical signoff from there.**