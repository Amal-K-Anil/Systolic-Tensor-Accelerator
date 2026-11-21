# Timing-Repair Experiments — Historical Reference

This directory preserves timing-closure experiments developed during the earlier `test_repo_5` phase of the Systolic Tensor Accelerator project.

These files are kept for future reference and comparison.

They are **not part of the active LibreLane flow** and should not be enabled automatically.

The current continuation branch is:

`latest-dev`

For the complete project state and continuation procedure, read the repository-level:

`PROJECT_STATUS.md`

---

## Purpose of This Directory

During physical-design timing closure, the design encountered several difficult electrical and timing problems, especially:

- maximum slew violations
- high-fanout control nets
- capacitance violations
- post-route electrical degradation
- interaction between repair stages and routing
- aggressive insertion of delay cells
- remaining hold violations after setup timing was improved

Several custom LibreLane/OpenROAD modifications were explored to improve closure beyond the standard flow.

The useful parts of those experiments are preserved here so that a future developer can study or selectively reuse them if timing closure is resumed.

---

# Preserved Files

## `config_before_postroute_feedback.yaml`

This is the physical-design configuration immediately before integration of the custom extracted-RC post-route slew-feedback experiment.

It is useful as a baseline when comparing how the feedback experiment changed the flow.

---

## `config_postroute_feedback.yaml`

This is the later experimental configuration in which normal detailed routing was replaced by the custom feedback-enabled step:

```yaml
OpenROAD.DetailedRouting: OpenROAD.DetailedRoutingWithSlewFeedback
```

The following experimental variables were enabled:

```yaml
POST_ROUTE_SLEW_FEEDBACK: true
POST_ROUTE_SLEW_CORNER: max_ss_125C_4v50
POST_ROUTE_SLEW_MAX_ITERATIONS: 8
POST_ROUTE_SLEW_SDC_FILE: dir::chip_top.sdc
```

The feedback corner was therefore:

```text
max_ss_125C_4v50
```

with a maximum of eight feedback iterations.

This configuration should not be used as the current project configuration.

The active configuration is:

`librelane/config.yaml`

on `latest-dev`.

### Independent configuration change

The later feedback configuration also changed:

```text
ERROR_ON_MAGIC_DRC
```

from:

```text
False
```

to:

```text
True
```

This was not inherently part of the extracted-RC feedback algorithm.

---

# 1. Post-GRT Design-Repair Experiment

File:

`repair_design_postgrt.tcl`

The standard LibreLane post-global-route design-repair script was modified to perform an additional repair cycle.

The experimental sequence was approximately:

1. Estimate parasitics after global routing.
2. Run the normal `repair_design`.
3. Legalize cells.
4. Run global routing.
5. Re-estimate parasitics.
6. Run a second `repair_design`.
7. Use a stronger slew margin during the second pass.
8. Legalize again.
9. Run another global route.

The second repair pass used:

```text
-slew_margin 31
```

The intention was to reduce remaining slew violations after the normal post-GRT electrical-repair stage.

This experiment was useful for investigating additional repair effort after routing, but it did not become the final recommended flow.

---

# 2. Detailed-Routing Antenna Experiment

File:

`drt.tcl`

A small modification was made to the detailed-routing script during antenna-repair investigation.

The standard rerouting call:

```tcl
drt_run $i {*}$drt_args
```

was changed to:

```tcl
drt_run $i {*}$drt_args -no_pin_access
```

after antenna repair.

This was an experimental workaround related to rerouting after antenna-diode insertion.

It is preserved only for reference.

---

# 3. Extracted-RC Post-Route Slew Feedback

This was the most extensive timing experiment preserved here.

Relevant files:

- `postroute_feedback.py`
- `steps_init_with_postroute_feedback.py`
- `postroute_slew_feedback/merge_patch.sh`
- `postroute_slew_feedback/repair_extracted.tcl`
- `postroute_slew_feedback/repair_residual_noncore.tcl`
- `postroute_slew_feedback/replay_and_grt.tcl`
- `postroute_slew_feedback/run_feedback.sh`

The custom LibreLane step was registered as:

```text
OpenROAD.DetailedRoutingWithSlewFeedback
```

and experimentally substituted for:

```text
OpenROAD.DetailedRouting
```

---

## Why It Was Developed

Earlier timing-repair stages operate using estimated parasitics.

After detailed routing and RC extraction, actual routed parasitics may reveal additional slew or capacitance violations that were not accurately represented earlier.

The purpose of this experiment was therefore to create a feedback loop that used **post-route extracted RC information** when deciding how to repair remaining electrical violations.

---

## High-Level Feedback Sequence

The experimental process included combinations of:

1. Start from a clean physical-design checkpoint.
2. Apply accumulated cell-replacement ECO changes.
3. Legalize modified cells.
4. Run a fresh global route.
5. Run detailed routing.
6. Extract RC parasitics.
7. Perform timing/electrical analysis using the selected corner.
8. Identify remaining slew/capacitance violations.
9. Run repair operations.
10. Record cell master changes as an ECO patch.
11. Merge the new patch with previous changes.
12. Replay the cumulative patch from the clean checkpoint.
13. Repeat routing, extraction, and analysis.
14. Stop when closure improved sufficiently or the iteration limit was reached.

The design goal was to avoid relying on manually hard-coded synthesized instance names.

Repair decisions were generated from the routed design itself.

---

# Custom LibreLane Step

## `postroute_feedback.py`

This Python file implements the experimental LibreLane step:

```text
OpenROAD.DetailedRoutingWithSlewFeedback
```

The step extends normal detailed routing with extracted-RC feedback.

Its configuration variables include:

```text
POST_ROUTE_SLEW_FEEDBACK
POST_ROUTE_SLEW_CORNER
POST_ROUTE_SLEW_MAX_ITERATIONS
POST_ROUTE_SLEW_SDC_FILE
```

It coordinates the OpenROAD scripts used for:

- routing
- RC extraction
- timing analysis
- repair
- ECO generation
- ECO replay
- iteration control

---

## `steps_init_with_postroute_feedback.py`

This file preserves the modified LibreLane step-registration file.

The relevant addition registered:

```python
from . import postroute_feedback
```

Without registration, the custom step would not be discoverable by LibreLane.

This file is preserved only as documentation of how the experimental step was integrated.

---

# Feedback Helper Scripts

## `postroute_slew_feedback/repair_extracted.tcl`

This script:

- loads the routed design
- reads extracted SPEF parasitics
- reports max-slew and max-capacitance violations
- runs `repair_design`
- detects cell-master changes
- records those changes into a patch file
- writes the repaired OpenDB database

The generated patch captures instance/master substitutions rather than preserving the entire modified database as the only source of truth.

---

## `postroute_slew_feedback/replay_and_grt.tcl`

This script replays a cumulative ECO patch onto a clean checkpoint.

It then:

1. replaces the specified cells
2. legalizes the modified placement
3. performs a fresh global route
4. writes updated ODB and DEF views

This allowed repair decisions to be replayed reproducibly rather than progressively modifying one increasingly altered checkpoint.

---

## `postroute_slew_feedback/merge_patch.sh`

This helper merges older and newer ECO replacement patches.

For each instance, the latest selected master is retained.

This allows multiple feedback iterations to build a cumulative repair patch.

---

## `postroute_slew_feedback/repair_residual_noncore.tcl`

This script investigates residual violations involving non-core loads.

For a violating endpoint it attempts to:

- identify the load instance
- identify the driving instance
- avoid applying the fallback to ordinary standard-cell core loads
- locate a stronger compatible master in the same family
- replace the driver with the next stronger available cell
- record the resulting replacement patch

This was a specialized fallback experiment and should not be treated as a general-purpose repair mechanism.

---

## `postroute_slew_feedback/run_feedback.sh`

This script orchestrates the iterative feedback procedure.

Its responsibilities include:

- creating per-iteration working directories
- replaying cumulative ECO patches
- running global routing
- running detailed routing
- performing RC extraction
- preparing timing environments
- generating intermediate netlists
- checking electrical violations
- invoking repair stages
- merging new ECO patches
- continuing through repeated iterations

The default experimental values included:

```text
FB_CORNER=max_ss_125C_4v50
FB_MAX_ITERATIONS=8
```

---

# Alternative Output-Processor Timing Architecture

File:

`output_processor_positive_slack_reference.sv`

This is an older alternative implementation of `output_processor`.

It was originally saved as:

```text
out_pro_pos_slack.txt
```

during timing optimization.

It is preserved because it represents a materially different datapath architecture that was associated with a positive-slack timing experiment.

---

## Architectural Differences

The preserved implementation uses a three-stage serialization structure involving:

- per-row column selection
- registered column-selection data
- separate row selection
- registered result data
- registered quantized output
- replicated local column counters
- one global pipeline advance/stall condition

The pipeline stalls as a unit when the output register contains valid data and the downstream interface is not ready.

The column-selection control was replicated per row to reduce fanout.

The implementation also used the registered one-cycle `output_done` behavior associated with final-result transfer.

---

## Important Warning

This file is **not the current RTL**.

The active implementation is:

`src/core/output_processor.sv`

on `latest-dev`.

Do not replace the active implementation with this reference file without:

- functional simulation
- cocotb verification
- synthesis comparison
- timing analysis
- physical-design rerun

It exists specifically as an alternative architecture that may be useful if the output serialization datapath becomes timing-critical again.

---

# Relationship to the Current `latest-dev` Flow

The experiments in this directory predate the final preserved development state.

Several improvements discovered during later work are already part of `latest-dev`, including:

- replicated high-fanout control registers
- replicated feeder valid control
- replicated output-processor clear distribution
- replicated local column state
- `(* keep *)` attributes
- Yosys preservation of those attributes
- updated cocotb verification
- padless top-level integration
- ACE2 physical-design configuration
- delay-cell family exclusion
- post-GRT timing repair
- cleaner timing-direction settings

These later improvements should remain the starting point.

---

# Delay-Cell Finding

A particularly important later discovery was that OpenROAD repair could insert large numbers of GF180 delay cells.

The relevant families included:

```text
dlya_*
dlyb_*
dlyc_*
dlyd_*
```

Those insertions significantly degraded setup timing.

The later active configuration therefore excludes the delay-cell families.

This direction produced substantially better setup timing than the earlier timing-repair experiments preserved here.

---

# Timing Context

The best later completed timing run used:

```text
GRT_RESIZER_HOLD_SLACK_MARGIN: 2.5
```

and achieved positive setup slack across the important analyzed corners.

The worst remaining hold violation was approximately:

```text
-0.038 ns
```

in the fast corner.

Electrical violations, especially slew and fanout, were still present.

The active configuration was subsequently changed to:

```text
GRT_RESIZER_HOLD_SLACK_MARGIN: 2.6
```

but that run failed before meaningful timing repair because of an OpenDB write I/O error.

Therefore the 2.6 setting should be considered **unvalidated**.

See `PROJECT_STATUS.md` for the full timing results and continuation state.

---

# Recommended Use of These Files

If physical-design timing closure is resumed:

1. Start from `latest-dev`.
2. Use the active RTL and active `librelane/config.yaml`.
3. Ensure the active LibreLane synthesis override is enabled.
4. Reproduce the current physical flow first.
5. Measure the actual remaining timing/electrical problems.
6. Consult this directory only if additional repair approaches are needed.
7. Reintroduce experiments individually and measure their effect.
8. Do not replace the complete active flow with these historical scripts in one step.
9. Treat `output_processor_positive_slack_reference.sv` as an architectural comparison only.

These files are preserved so that the timing-repair engineering work remains available without making experimental behavior part of the default project flow.