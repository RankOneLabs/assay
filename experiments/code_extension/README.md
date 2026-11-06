# Code extension experiment

## Operator runner

Hosted launches use the shared repository-agent OpenRouter backend and its
existing pinned model/provider catalogue. Set `route` to that exact endpoint,
model and provider, `profile` to `openrouter`, `bounds` to
`ExtensionAgentSettings.for_model(model)`, and pricing to
`{"basis":"openrouter-pinned-price-ceilings","conservative_request_bound_usd":null}`.
`prepare` needs no credential or Smithers routing file. For `execute`, provide
`OPENROUTER_API_KEY` through the environment. Both the route probe and every
model turn use the shared worst-case request reservation and inline billed
cost accounting, with separate per-attempt and run caps. The extension journal
records each reservation before dispatch and preserves known charges on provider
errors; unsent requests release their reservations. Unknown charges halt the run.
Hosted byte and output limits reuse the verification pilot's envelope; hosted
context capacity is recorded as unavailable until independently observed.

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
| `profile` | `openrouter` for hosted models; the qualified machine name for Smithers. |
| `system_prompt_digest`, `tool_schemas_digest` | Literal ce-v1 pins in `protocol.py`. |
| `image_digest` | Observed sha256 image digest in every chosen manifest. |
| `bounds` | Complete `ExtensionAgentSettings.for_model(model)` envelope. |
| `repeats`, `randomization_seed`, `concurrency` | Full-grid repeats, a recorded metadata seed, and concurrency 1. The seed does not randomize dispatch. |
| `dispatch_schedule` | `subject-rotated-v1`, the existing shared planner schedule; also the default for older configurations. |
| `pricing` | Hosted: pinned provider price ceilings and inline billed cost. Local Smithers: a positive explicit conservative request bound. |
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
coverage, and the selected dispatch schedule.

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

The existing four-shape comparison is independent of the proposed three-task
baseline pilot. Its per-arm full-path qualification records live in
`fixtures/stage-pass-through/qualification/arms/<arm>/`. An example hosted
configuration is in `examples/hosted-shapes.json`; its dollar limits are
illustrative operator inputs. `prepare` compiles its twenty cells (four shapes,
five repeats) without model requests. `execute` first makes one charged route
probe, then retains every dispatched attempt and its independent grade. No paid
calibration or study run is included in the qualification evidence.

The existing `pilot` (context defaults) and `pointer-root` scenarios also have
full-path sidecars and gates. Together with `dispatch-handler`, these are three
baseline tasks: five repeats produce fifteen attempts. Context defaults and
pointer-root share an image and can use one plan; dispatch-handler retains
its earlier qualified image and needs its own plan. Keep those plans separate
from the four-arm pass-through cohort because the planner also requires a
common arm set within each plan. Across the three plans,
five repeats cover all four existing scenarios in thirty-five attempts per
model. This is a descriptive difficulty pilot; only pass-through compares
matched shapes, and the pointer task is an easy control.
Context defaults is now qualified offline without the old local routing-file
pin; its task, tree, tests, original patches and check records are unchanged.

The supported inexpensive hosted routes include `mistralai/ministral-14b-2512`
on `mistral/zdr` and `qwen/qwen3.8-27b` on `deepinfra/bf16`. Select each exact
route with its `ExtensionAgentSettings.for_model(model)` envelope and freeze
separate configurations and spend caps for the baseline and shape cohorts.

For a retained study archive, report and replay from `experiments/` with:

```sh
python -m code_extension.run report \
  --archive /absolute/path/to/study/archive \
  --output ../.assay/extension-report
python -m code_extension.run regrade \
  --archive /absolute/path/to/study/archive \
  --image sha256:d0da319d2e141415c1c41ccea44983e8986944e5ae45b53652a9c104c462c4ee \
  --output ../.assay/extension-replay
```

Reporting requires the locked Node analyzers and fixture TypeScript dependencies
to be installed before measurement. Replay reads the retained fixture identity
and its original test groups; a changed checkout cannot substitute new tests.
Only legacy archives without a retained fixture use checkout manifests.
Generated study data belongs outside this source repository.

An interrupted grid can continue with its original plan and partial manifest:

```sh
python -m code_extension.resume \
  --plan STORE/plans/<digest>/plan.json --authorize sha256:<digest> \
  --store STORE --manifest sha256:<partial-manifest>
```

Resume cross-checks the durable attempt journal, retains terminal attempt and
evaluation identities, and dispatches only coordinates never claimed. A spending
refusal recorded before dispatch can be replaced by that coordinate's first
attempt. The original manifest and recovery checkpoint remain retained, and
the original runtime, grid, wall allowance, per-attempt cap and total cap still
apply. The wall allowance counts retained attempt and grading time, so a pause
before resuming does not consume it.
By default, an unknown bill continues to block dispatch. An operator can supply
`--accept-unknown "reason for accepting full reserved charges"` to charge each
unknown request at its entire reservation for admission while keeping its actual
cost explicitly unknown. This cannot acknowledge a known over-reservation bill,
increase a cap, or redispatch an already claimed attempt.

Resume refuses a cancelled or interrupted run, because its work may still be
running and a cancelled call records no used time. This includes a run cancelled
during grading; its remaining coordinates need a separately authorized plan. It
also refuses a checkpoint with no retained attempt, because
the original wall allowance cannot be restored from it; no attempt has run, so
start that plan again with `execute`.

The separate three-task baseline pilot's launch preconditions remain open.
Cross-module-event is feasible at
the upstream pin, but config-plugin lacks a configuration-driven loading path,
so there is **no frozen three-scenario pilot configuration or fifteen-attempt
plan**. No attempt for that proposed three-task baseline has been dispatched. A reviewed
scenario selection and passing qualification for all three selected subjects
are required before a pilot freeze. The operator must then review a model-free
scripted full path, a route probe counted as live work, the exact endpoint,
model and provider with a qualified envelope entry, a pricing basis or an
explicit conservative per-request bound, and an approved plan with per-attempt
and total spend caps. Prompt, tool, fixture and image identity checks must
reject drift. The charged route probe currently halts with
`billing_uncertain` until a Smithers billed-cost source exists. The 120
per-cell tool-call bound remains unavailable because extension mode cannot
enforce it.

## WP6 candidate feasibility review

The checkpoint is `f3b3ffca43e43672ff2f58ab797d65c7532aaed8`. The
earlier search covered only the dispatch-handler's deliberately extracted
62-file start tree, not the upstream pin. A fresh feasibility extraction from
the pin used:

```sh
git -C /home/steve/codes/rol/oakridge archive f3b3ffca43e43672ff2f58ab797d65c7532aaed8 tsconfig.json oakridge-dbos/src oakridge-dbos/tests/invalidation-events.test.ts oakridge-dbos/package.json oakridge-dbos/tsconfig.json
```

The extracted 125 files total 706,674 bytes before dependency installation,
within both fixture package limits. This review extraction is under `/tmp`,
not a frozen worker tree. It includes `src/domain/run-event.ts` (event schema,
`RunEvent` export and `projectRunEvent`),
`src/storage/postgres-operators.ts` (`PostgresOperatorProjectionRepository.list_run_events`),
`src/http/invalidation-events.ts` (`createInvalidationEventApp`), and
`src/http/app.ts` (the producer-to-consumer wiring). The upstream
`tests/invalidation-events.test.ts` imports only `bun:test` besides source
modules. The Postgres-backed producer accepts an injected `SqlExecutor` whose
`query` method returns rows; the real query and projection can be exercised
with a fake executor and without a live Postgres server. The SSE consumer also
takes injected callbacks. The extracted upstream `package.json` already names
`hono`; a runnable frozen fixture must carry it in its dependency lock. The
upstream SSE test passed all eight checks, and an additional temporary test
projected a SQL row through the injected producer without Postgres.
Cross-module-event is feasible at the pin, pending a fully qualified fixture.
With the pin's root `tsconfig.json` included and the upstream installed dependencies supplied, the
review extraction also passed `tsc --noEmit -p tsconfig.json`.

At the same upstream pin, `compileWorkflowDefinition(definition, registry?)`
accepts an injected registry, `src/runtime/executor-registry.ts` registers
executors imperatively, and `src/http/configuration.ts` reads configuration.
None loads stage plugins from configuration. The plugin arm of the separately
committed stage-pass-through subject contains `stage-plugin-config.json` and
`stage-plugins.ts`, but its README identifies both as authored adaptations
absent at the pin. Reusing that arm would invent the production loading path
that config-plugin is meant to extend. The proposed replacement for review is
an **injected stage compiler registry** scenario using the existing registry
argument and visible compiler contract. It would not claim configuration
loading and has not been substituted or qualified.

The two candidate `task.md` files retain the requested behaviors and
requirements-to-intended-tests tables. They remain review drafts: there are
no committed start trees, sidecars, hidden groups, qualification patches or
gate records for them. The committed qualification manifests remain
unchanged, and the descriptive report still reflects only committed evidence.

The independent offline evidence rehearsal is
`code_extension/tests/test_code_extension_report.py::test_committed_qualification_and_scripted_archive_reproduce_and_export`.
It binds the existing dispatch-handler qualification manifest and records,
submits a model-free scripted `write_file` and `submit_output` through the
production bridge with a fake sandbox, and keeps the resulting run archive
under pytest's temporary directory. It renders `REPORT.md`, `ledger.csv` and
`ledger.json` twice and compares exact bytes. It exports the run manifest's
object closure, accepts only the expected `incomplete_run` observation because
the scripted rehearsal has no evaluator record, and confirms that changing an
exported object makes verification fail for integrity. The archive is test
output, not committed run evidence; the committed report does not gain a live
attempt row.

## Matched-task example configs

`examples/hosted-matched-tasks-ministral.json` and `-qwen.json` prepare the two
new tasks across all four shapes at five repeats: 40 attempts per route, as two
separate plans. They differ only in route, cohort label and recorded seed. Their
caps are illustrative and authorize nothing, and revalidate route availability and
pricing before any live launch.

```sh
uv run python -m code_extension.run prepare --config code_extension/examples/hosted-matched-tasks-ministral.json --store .assay-extension
```

`prepare` dispatches nothing and needs no API key. The launch summary under
`STORE/plans/<digest>/` names every coordinate, the route, the image, the prompt,
tool and scope identities, the caps, the worst-case serial duration and the billing
recovery default.

`studies/matched-tasks-2026-11/` holds the matched-task cohorts, with their analysis,
billing recovery and store policy in `study-plan.md`. A cohort's caps authorize nothing
until a launch names it. `python -m code_extension.reachability --store S --plan sha256:...`
prints each attempt's stop, request count, verdict and reachability split.

## Running several plans

A cohort file lists plans in launch order under one combined cap. Preparing it
freezes every plan, then writes `cohort.json` and a combined launch summary to
`STORE/cohorts/<digest>/`. It dispatches nothing and needs no API key.

```sh
uv run python -m code_extension.launch prepare --cohort code_extension/examples/hosted-matched-tasks.json --store .assay-extension
uv run python -m code_extension.launch execute --cohort .assay-extension/cohorts/<digest>/cohort.json --authorize sha256:<digest> --store .assay-extension
uv run python -m code_extension.run status --store .assay-extension --cohort sha256:<digest>
```

Preparing refuses plan caps that total more than the combined cap. Each plan's
spending gate refuses any request whose reservation would pass its cap, so reservations
cannot exceed the combined cap. A provider bill above its reservation can still take a
plan past its cap by that excess. The plan then halts, `--accept-unknown` cannot clear
it, and later plans do not start.

`execute` checks every plan before the first paid request, then runs them one at a
time and stops at the first halt. It never retries, replaces or resumes a cell. Each
plan's journal records how its last run ended, so launching again skips finished
plans and refuses a partial one. A lock in each plan's directory holds one process per
plan across `execute`, `resume` and any cohorts sharing it, and a killed process
releases it. Continue a halted plan with `code_extension.resume`,
using the `manifest_ref` that status prints, then launch again for the plans after it.
Unknown charges still need an explicit `--accept-unknown` on each resume.

A plan with no `manifest_ref` cannot resume, because no manifest records which cells
ended. A failed route probe and a process killed mid-run both leave one. `execute` and
the launcher will not restart it, and preparing the same configuration returns the same
plan. To run its cells, change the configuration's `cohort` label, leave finished plans
out of the cohort file, and prepare a new cohort, which needs its own authorization. The
old journal keeps its charges, so count that plan's conservative cost against the total
authorized before setting the new caps.

`status` reads durable records and writes nothing. Without `--cohort` it reports every
plan in the store. For each plan it gives planned, started, terminal, normally
completed, evaluated, passed and unstarted counts, the active coordinate, last
activity, halt reason, measured and conservative cost, and unknown charges. Conservative
cost counts an unknown or unsettled request at its full reservation.

- Grading follows the last attempt and is retained only in the run manifest, so
  `evaluated` and `passed` stay null until a plan has settled once.
- `in_progress` also describes a killed process. Compare `last_activity` with the clock.
- `unrecorded` marks a journal from before runs recorded their own end. Its cost and
  attempt counts are still correct, but it has no timestamps.

## ce-v1 contract and protocol

`contract.py` defines `assay-extension-scenario-sidecar/0.1.0` alongside the
unchanged fixture manifest. The sidecar declares six contracts per scenario:
writable implementation scope; protected test, dependency and configuration
files; a requirements-to-tests table; reference and incomplete patch inventory
with intent; and content-addressed refs for leak scan, access probe, no-op,
scripted submission and double reproduction evidence. The fixture cohort will
load and bind these declarations to its committed scenarios.

A scenario opts into agent-written tests by adding `tests/agent/` to its writable
scope. The bridge then tells the agent how to run them and that they are not
graded. The evaluator grades against the same declared scope the worker enforces,
removes `tests/agent/` before preflight, and the changed-path measure ignores it.
Shipped tests, dependency files and root configuration stay protected.

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
| `oakridge-dbos-stage-status-report` | The same four matched shapes | Compile a `status_report` stage with a typed configuration, documented defaults and a normalized executor contract | No | `f3b3ffca43e43672ff2f58ab797d65c7532aaed8` |
| `oakridge-dbos-stage-collect-artifacts` | The same four matched shapes | Compile a `collect_artifacts` stage using the existing `artifact_collection` contract | No | `f3b3ffca43e43672ff2f58ab797d65c7532aaed8` |
| `oakridge-dbos-pointer-root` | Local utility edit | Accept `#` as the root JSON pointer in the shared pointer reader | Yes: the edit needs no nonlocal registration or caller tracing | `f3b3ffca43e43672ff2f58ab797d65c7532aaed8` |

The stage scenario's four trees live under `repository/<arm>/`; the pointer
control has one `repository/` tree. Each added scenario keeps its hidden groups
and per-arm patches outside those trees. `qualification/` binds the observed
image, tree, patch, and check-group digests to the baseline, reference, and
negative verdicts. The fixture suite validates every committed tree and
record. The pilot's existing qualification manifest and frozen harness remain
unchanged.
