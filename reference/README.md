# Reference Material

This directory contains historical and comparison material preserved to support future continuation of the Systolic Tensor Accelerator project.

The files under `reference/` are **not the active implementation** unless explicitly stated otherwise.

For current development, use the `latest-dev` branch and read the repository-level:

`PROJECT_STATUS.md`

before making changes.

---

## Directory Purpose

The active project files remain in the normal repository locations:

- `src/` — current accelerator RTL
- `cocotb/` — current verification tests
- `librelane/` — current physical-design configuration
- `info.yaml` — current organizer/reviewer pad assignment
- `tools/librelane_override/` — active project-local LibreLane synthesis override

The `reference/` directory exists only to preserve older implementation context, previous physical-integration information, and timing-repair experiments that may still be useful for comparison or future investigation.

---

## `info_ace2_last_tested.yaml`

This file preserves the older `info.yaml` that was present during the last locally exercised ACE2 physical-design work.

It represents the earlier ACE2-era logical/pad assignment that was used while the experimental ACE2 floorplan was being developed.

It should **not** replace the repository-root `info.yaml`.

The root `info.yaml` is newer and reflects the later organizer/reviewer requirements, including:

- explicit VDD
- explicit VSS
- explicit unused/NC positions
- WEST/NORTH pad allocation
- shared `data[7:0]`
- A, B, and OUT control signals

The newer root `info.yaml` was introduced after the last ACE2 physical-design/timing runs.

Therefore:

- `info.yaml` = current integration definition
- `reference/info_ace2_last_tested.yaml` = historical ACE2-era reference

The current root pin assignment and the old ACE2 physical implementation have not yet been fully reconciled and physically validated together.

---

## `timing-repair/`

This directory preserves timing-closure experiments developed during the earlier `test_repo_5` work.

These experiments include:

- a modified post-global-route design-repair flow
- a detailed-routing antenna-repair modification
- an extracted-RC post-route slew-feedback loop
- custom LibreLane step registration
- before/after timing-flow configurations
- an older alternative `output_processor` implementation associated with a positive-slack timing experiment

These files are preserved because the ideas may be useful if physical-design timing closure is resumed.

They are **not part of the current active LibreLane flow** and should not be enabled automatically.

See:

`reference/timing-repair/README.md`

for the complete explanation of each preserved file and experiment.

---

## Active LibreLane Override Is Not Reference Material

The project also contains:

`tools/librelane_override/`

This directory is intentionally **outside** `reference/`.

It is active project infrastructure required to reproduce the latest development flow.

The important modification is in:

`tools/librelane_override/librelane/scripts/pyosys/synthesize.py`

and preserves intentionally replicated RTL registers carrying the `(* keep *)` attribute.

The override must be included in `PYTHONPATH` when running the preserved flow.

See `PROJECT_STATUS.md` for the exact command and explanation.

---

## Recommended Use

A future developer should normally:

1. Checkout `latest-dev`.
2. Read `PROJECT_STATUS.md`.
3. Work from the active RTL/configuration in the normal repository directories.
4. Use `tools/librelane_override/` when running LibreLane.
5. Consult `reference/` only when historical comparison or earlier implementation context is needed.

Do not copy historical reference files back into the active flow without understanding why the newer implementation replaced them.