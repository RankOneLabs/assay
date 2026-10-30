# Code extension experiment

## ce-v1 contract and protocol

`contract.py` defines `assay-extension-scenario-sidecar/0.1.0` alongside the
unchanged fixture manifest. The sidecar declares six contracts per scenario:
writable implementation scope; protected test, dependency and configuration
files; a requirements-to-tests table; reference and incomplete patch inventory
with intent; and content-addressed refs for leak scan, access probe, no-op,
scripted submission and double reproduction evidence. The fixture cohort will
load and bind these declarations to its committed scenarios.

`protocol.py` identifies the one-turn extension protocol as `ce-v1` version
`1.0.0`. Literal digests freeze the bridge's system prompt, a four-part rendered
task witness, ordered tool schemas and `submit_output` submission schema.
Individual trials must additionally record the digest of the rendered
`instruction.md` they deliver. The worker cohort will wire the new renderer to
the bridge; this cohort defines the renderer and pins before dispatch changes.

Calibration defaults are 900 seconds per attempt, 60 model requests, 8,192
output tokens per request and 32 KiB of tool output. The served model context
and 120-second request timeout are explicit settings. The 120 per-cell tool-call
ceiling is recorded as unavailable: extension mode does not enforce that limit,
because the loop honors it only in pilot mode. Sampling remains unset unless a
route requires it, with requested and provider-reported values held separately.

The operator authorized the lockstep update to
`integrations/pier/config/code_extension.yaml`. The rebuilt
`assay-code-extension:ce-v1-bounds` image inspected as
`sha256:d0da319d2e141415c1c41ccea44983e8986944e5ae45b53652a9c104c462c4ee`.
The pilot, pointer-root and stage-pass-through fixtures were requalified against
that observed digest; their baseline, reference and negative verdicts matched
the previous qualified records.

This package fixes the Spec 3 domain shape before any study runs. The fixture
manifest version `assay-fixture-manifest/0.3.0` declares one factor in `arm_set`
and one or more scenarios. Each scenario pins its checkpoint slice, bounded
feature request, visible requirements and named visible and hidden test groups.
Each arm records its tree, task prompt, private reference patch and negative
controls by digest, plus three retained qualification outcomes.

`arms.py` fixes the factor tags and the first run's single `baseline` arm.
Member arm ids for other factors are declared by the manifest. Before planning,
call `manifest.require_qualified()`; before dispatch, call
`shape.validate_worker_grid` with the manifest's `arm_set` as `arm_ids`.
The grid validator requires every declared subject, arm and worker repeat
exactly once and refuses qualification-smoke subjects.

This package belongs to the existing `experiments` uv project. The pilot and
two additional committed scenarios live under `fixtures/`; worker dispatch and
the evaluator are supplied by separate cohorts.

## Initial scenario roster

The first three committed subjects use the pinned oakridge-dbos checkpoint
`f3b3ffca43e43672ff2f58ab797d65c7532aaed8`. The three subject ids are
distinct from every refused qualification-smoke id (`oakridge-dbos-smoke-wf12`,
`oakridge-dbos-smoke-edit-wf13`, and `oakridge-dbos-verification-pilot-edit`).

| Subject id | Shape realized | Shared feature request | Negative control? | Pin |
| --- | --- | --- | --- | --- |
| `oakridge-dbos-context-defaults` | Cross-module extension in the qualified baseline pilot | Optional context binding defaults | No | `f3b3ffca43e43672ff2f58ab797d65c7532aaed8` |
| `oakridge-dbos-stage-pass-through` | Modular dispatch, central switch or registry, cross-module extension, and configuration-driven plugin as matched arms | Compile a `pass_through` stage whose outputs release immediately and whose materialization is scalar | No | `f3b3ffca43e43672ff2f58ab797d65c7532aaed8` |
| `oakridge-dbos-pointer-root` | Local utility edit | Accept `#` as the root JSON pointer in the shared pointer reader | Yes: the edit needs no nonlocal registration or caller tracing | `f3b3ffca43e43672ff2f58ab797d65c7532aaed8` |

The stage scenario's four trees live under `repository/<arm>/`; the pointer
control has one `repository/` tree. Each added scenario keeps its hidden groups
and per-arm patches outside those trees. `qualification/` binds the observed
image, tree, patch, and check-group digests to the baseline, reference, and
negative verdicts. The fixture suite validates every committed tree and
record. The pilot's existing qualification manifest and frozen harness remain
unchanged.
