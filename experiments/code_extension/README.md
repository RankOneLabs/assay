# Code extension experiment

## Operator runner

Run these commands from `experiments/`:

```sh
python -m code_extension.run qualify --scenario dispatch-handler --image sha256:<digest> --verify-committed
python -m code_extension.run scripted --scenario dispatch-handler --image sha256:<digest> --store .assay-extension
CODE_EXTENSION_ROUTING_CONFIG=/absolute/path/to/smithers-routing.yaml python -m code_extension.run prepare --config run-config.json --store .assay-extension
CODE_EXTENSION_ROUTING_CONFIG=/absolute/path/to/smithers-routing.yaml python -m code_extension.run execute --plan .assay-extension/plans/<digest>/plan.json --authorize sha256:<digest> --store .assay-extension
```

`qualify` delegates to the existing scenario qualifier. `python -m
code_extension.qualify` retains its full argument surface, including
`--evidence-dir` and `--manifest`. `scripted` enters the existing model-free
scripted worker and independent evaluator. `python -m code_extension.diagnose`
remains the separate replay diagnostic and cannot write a verdict.

`run-config.json` is a closed JSON object. Every field is required:

| Field | Meaning and source |
| --- | --- |
| `scenario_qualifications` | Array of `{scenario, manifest_digest}` entries. The digest is the exact byte digest of that scenario's committed `qualification/manifest.json`. |
| `cohort` | Operator's calibration or pilot cohort identity; each gets its own configuration and cap. |
| `route` | Exact `{endpoint, model, provider}` from the authorized extension route matrix. |
| `profile` | The qualified Smithers machine name used to resolve that model. |
| `system_prompt_digest`, `tool_schemas_digest` | Literal ce-v1 pins in `protocol.py`. |
| `image_digest` | Observed sha256 image digest in every chosen manifest. |
| `bounds` | Complete `ExtensionAgentSettings.for_model(model)` envelope. |
| `repeats`, `randomization_seed`, `concurrency` | Declared full-grid repeats, recorded seed, and concurrency 1. The current shared planner still uses `subject-rotated-v1`; see the open order decision below. |
| `pricing` | `{basis, conservative_request_bound_usd}`. Local Smithers has no billed price, so a positive explicit request bound is required. |
| `per_attempt_cap_usd`, `total_cap_usd` | Positive dollar caps chosen by the operator; neither has a default. |

Money values in JSON are decimal strings. Secrets are supplied through the
transport environment, never through this configuration or its archive.
Credential-like keys or values in the configuration are refused.

`prepare` verifies each manifest, qualification outcome and evidence digest,
the scripted full-path record, fixture trees, hidden groups, image, route,
envelope, prompt and tools. It compiles the shared full-grid plan, validates
every coordinate, and writes canonical plan bytes, a configuration copy and a
launch summary under `STORE/plans/<digest>/`. It dispatches nothing. A missing
record produces `scripted full path qualification is absent`; drift names the
fixture, image, route, prompt or tool identity. An unset cap raises
`MissingSpendCap`; absent usable pricing raises `UnknownPricing` or
`pricing_basis_unusable`. An absent routing file raises
`routing_artifact_unavailable`. The summary lists concrete cells, model,
maximum requests, attempts, effective limits, estimated and maximum spend,
coverage, and the unresolved dispatch-order question.

`execute` requires the original stored plan, its exact digest, and the frozen
configuration. The shared authorizer rejects noncanonical bytes and the
shared executor rechecks the snapshot and cell list. A digest mismatch names
both digests. Each cell attempt identity is fsynced before dispatch; every
turn has a separate fsynced reservation. On resume, unfinished reservations
are charged at their bound and halt with `billing_uncertain`. A used attempt
identity is never dispatched again. The route probe is a live, authorized
request against the same cap; it confirms the worker model and requested
output bound. The shared spend ledger reserves before each request and halts
with `budget_exhausted` or `billing_uncertain` when the cap or billing
certainty fails. Smithers currently reports no billed cost, so the probe
halts at `billing_uncertain` after its bound is charged. It cannot authorize
subsequent cell dispatch until a billed-cost source is available.

Keep the store, runs root and archive root on durable project storage, away
from the OS temp directory. Waking a GPU worker power-cycles it and wipes its
temp directory, which would erase the run before evidence can be read.

Pilot launch preconditions are still open. Requalify pilot, pointer-root and
dispatch-handler together against one observed image, retaining passing
scripted full-path records for each, before preparing the fifteen-attempt
pilot. Resolve a Smithers billed-cost source before any live cell dispatch;
until then the charged route probe halts with `billing_uncertain`. These are
operator inputs to the launch gates, not code defects.

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
