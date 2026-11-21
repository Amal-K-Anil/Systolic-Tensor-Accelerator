# Project Status / Continuation Notes

This branch preserves the latest useful development state of the Systolic Tensor Accelerator so that the project can be resumed later.

## Branches

- `main`  
  Earlier committed baseline. This includes the successful dry-run/GDS-era work and the later reviewed `info.yaml` / export-control updates.

- `latest-dev`  
  Recommended branch for continuing development. It contains the latest optimized RTL, padless top-level integration, ACE2 physical-design work, timing experiments, and the required synthesis override.

- `timing-experiments`  
  Reference branch for older timing-closure and custom physical-design experiments from `test_repo_5`. It is not intended to be the default development base.

---

## Current Development State

The accelerator RTL is functionally developed and the important high-fanout optimizations have been incorporated.

The latest development work focused mainly on physical implementation and timing closure rather than functional RTL changes.

The latest physically exercised implementation used the experimental ACE2 floorplan.

Important optimized RTL files include:

- `src/core/accelerator_core.sv`
- `src/core/feeder.sv`
- `src/core/mac_unit.sv`
- `src/core/output_processor.sv`
- `src/core/systolic_array.sv`

The high-fanout `valid` and `clear` control structures were replicated locally in RTL to reduce fanout.

---

## Important Synthesis Override

Yosys originally merged intentionally replicated registers because they carried identical values. This recreated the large fanout problem even though the RTL contained replicated registers.

The required fix is contained in:

`/.python_override/librelane/scripts/pyosys/synthesize.py`

The only intentional difference from the installed LibreLane version is:

```python
d.run_pass("proc_dff")

# Preserve intentionally replicated control registers.
d.run_pass("attrmvcp", "-copy", "-attr", "keep")

d.run_pass("proc_memwr")
```

The corresponding RTL registers use `(* keep *)`.

The override must be active when running LibreLane, for example:

```sh
export PYTHONPATH="$PWD/.python_override${PYTHONPATH:+:$PYTHONPATH}"
```

The current Makefile does **not** automatically set this `PYTHONPATH`, so simply running `make librelane` may not use the synthesis override.

---

## Latest Physical-Design Direction

The latest clean flow used:

- LibreLane `Classic` flow
- `SYNTH_STRATEGY: "DELAY 4"`
- placement density around 50%
- `CTS_APPLY_NDR: none`
- `GRT_ALLOW_CONGESTION: false`
- placement mirroring enabled
- delay-cell families `dlya_*`, `dlyb_*`, `dlyc_*`, and `dlyd_*` excluded
- post-global-route timing repair enabled

The delay-cell exclusion was important because OpenROAD was inserting large numbers of delay cells during fanout repair, which badly degraded setup timing.

---

## Timing Status

Setup timing was successfully brought positive in the best completed runs.

The last fully completed useful timing experiment used:

`GRT_RESIZER_HOLD_SLACK_MARGIN: 2.5`

That run achieved positive setup slack in the important corners and reduced the remaining hold problem to approximately:

`max_ff hold ≈ -0.038 ns`

The remaining hold problem was essentially one short input-to-register path associated with `data[6]`.

Electrical cleanup was not fully complete. Slew, fanout, and some capacitance violations still remained, particularly in slow corners.

The configuration was then changed to:

`GRT_RESIZER_HOLD_SLACK_MARGIN: 2.6`

However, that run failed early while OpenROAD was writing an ODB file with an I/O/storage error. It did not reach the relevant timing stages.

Therefore:

- `2.5 ns` = last completed/validated hold-margin experiment
- `2.6 ns` = current configuration, but unvalidated

Do not assume the 2.6 ns setting is better until it is rerun successfully.

---

## ACE2 Floorplan

The last locally tested floorplan is:

`librelane/slots/slot_ace2.yaml`

It uses a 2235 × 2235 µm bounding area with two unavailable corner regions represented using placement, routing, and PDN obstructions.

This was an experimental configuration used before the final organizer-provided physical integration data was available.

The old `slot_a.yaml` was removed in this development state.

---

## Padframe / info.yaml Status

The root `info.yaml` comes from the newer reviewed `main` branch and reflects the later organizer requirements:

- explicit VDD
- explicit VSS
- explicit NC pads
- WEST/NORTH pad allocation
- A/B/OUT interfaces grouped consistently
- shared `data[7:0]` bus

This newer pin plan was agreed after the last ACE2 timing runs.

Therefore, the current root `info.yaml` should **not** be interpreted as having been physically validated together with the old ACE2 timing results.

The `reference/info_ace2_last_tested.yaml` file preserves the older `info.yaml` that was present when the ACE2 implementation was being tested.

---

## Top-Level Integration

The latest top level is padless.

Physical GF180 I/O cells are no longer instantiated directly inside `chip_top.sv`.

The external interface includes:

- `clk`
- `rst_n`
- `data[7:0]`
- A interface: `a_valid_i`, `a_last_i`, `a_ready_o`
- B interface: `b_valid_i`, `b_last_i`, `b_ready_o`
- OUT interface: `out_valid_o`, `out_last_o`, `out_ready_i`

The physical padframe is intended to be handled later during chip-level integration.

---

## Clock Constraint

The design was targeting:

- clock period: 40 ns
- frequency: 25 MHz

The SDC was updated for the padless logical interface.

---

## Recommended Starting Point

If continuing the project:

1. Start from `latest-dev`.
2. Keep the optimized RTL unless a specific functional issue is found.
3. Ensure the `.python_override` synthesis fix is active.
4. Review the final target floorplan/padframe requirements before rerunning physical design.
5. Reconcile the newer `info.yaml` pin plan with the final physical slot/DEF.
6. Rerun the flow with the current physical constraints.
7. Continue timing closure from the remaining hold/slew/fanout/capacitance issues.
8. Treat the `timing-experiments` branch only as a reference for older repair approaches.

The project had progressed beyond basic RTL functionality; the remaining work was primarily physical integration and signoff/timing closure.