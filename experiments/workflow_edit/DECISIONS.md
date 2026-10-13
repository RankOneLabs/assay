# Workflow edit decisions

This is the live decision record for the workflow edit study. Later cohorts
append decisions here as the study takes shape, including dispatch topology and
the provenance of provisional bounds.

## Scaffold

- **Arm names:** The four arm identifiers are `mess-00`, `mess-low`,
  `mess-mid`, and `mess-high`. Each satisfies `assay.models.Identifier`, so no
  escaping or aliasing layer is needed. Fixed names give later cohorts one
  vocabulary for configuration and reporting.
- **Grid validation:** The worker grid validator lives in this package. It
  checks the exact four arms and one cell per subject, arm, and worker repeat.
  Subject count and repeat count remain caller supplied. The DRY experiment's
  validator fixes a different population and grid, so this study does not use it.
- **Project layout:** This package is registered in the existing `experiments`
  uv project alongside `oakridge_history` and the other experiment packages.

## Execution ceilings

- **Plan-level capacity:** `assay-execution-plan/0.3.0` adds a typed `ceiling`
  beside `cost_estimate`, with limits for admitted cells, wall time, and active
  fleet occupancy. The ceiling applies to the whole grid, so it does not live
  in individual arm conditions. The shipped 0.1.0 and 0.2.0 plan shapes stay
  unchanged.
- **One reservation rule:** Cell dispatch and provider requests reserve through
  the same admission ledger before work begins. Dollar reservations retain the
  `budget_exhausted` halt; capacity uses `ceiling_exhausted`. Failed requests,
  retries, and tool-loop calls consume their reservation. Missing billing
  halts with `billing_uncertain` and never becomes a zero charge.
- **Recorded partial runs:** A ceiling halt stops new cells while every started
  cell gets a durable outcome. Evaluation records are created only for cells
  with execution outcomes; the remaining coordinates appear as missing in the
  incomplete manifest.
## Runtime image

- **Image identity:** Bind `BridgeIdentity.bridge_image_digest` from
  `docker image inspect --format '{{.Id}}'` on the built bridge image. A
  manifest that declares another digest fails with
  `ImageDigestMismatchError`. Each rebuild is a new fixture, even when its
  locked dependencies are unchanged.
- **Toolchain timing:** Node and TypeScript belong in the image before a trial
  starts. The trial has no network and performs no dependency installation.
  The fixture's Node `package.json` and `package-lock.json` live under
  `integrations/pier/workflow_edit/`, the bridge Docker build context. `npm ci`
  installs the locked tree in the Node build stage; the final image copies that
  tree and Node, while omitting npm so trials cannot install dependencies.
