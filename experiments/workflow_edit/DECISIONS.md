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
