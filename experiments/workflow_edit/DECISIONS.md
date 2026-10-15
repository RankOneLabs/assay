# Workflow edit decisions

This is the live decision record for the workflow edit study. Later cohorts
append decisions here as the study takes shape, including dispatch topology and
the provenance of measured qualification ceilings.

## Scaffold

- **Arm names:** The four arm identifiers are `mess-00`, `mess-low`,
  `mess-mid`, and `mess-high`. Each satisfies `assay.models.Identifier`, so no
  escaping or aliasing layer is needed. Fixed names give later cohorts one
  vocabulary for configuration and reporting.
- **Grid validation:** The worker grid validator lives in this package. It
  checks the exact four arms and one cell per subject, arm, and worker repeat.
  Subject count and repeat count remain caller supplied. The DRY experiment's
  validator fixes a different population and grid, so this study does not use it.
  Every qualification smoke subject (`settings.SMOKE_SUBJECT_IDS`) is refused.
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
  locked dependencies are unchanged. The bridge source is copied into the
  image, so a bridge code change is a rebuild too.
- **Toolchain:** oakridge-dbos runs its tests under bun (`bun test`,
  `bun:test`, extensionless ESM imports), so the image carries a digest-pinned
  bun 1.3.13 beside Node v22.21.1, and the locked tree is the one the pinned
  commit's own lock resolves: TypeScript 5.9.3, zod 4.4.3, @types/bun 1.3.13
  (bun-types 1.3.13, @types/node 25.6.0, undici-types 7.19.2; the last two
  pinned with npm `overrides`). The manifests live under
  `integrations/pier/workflow_edit/`; `npm ci` installs them in the Node build
  stage and the final image omits npm.
- **No install in a trial:** The locked tree sits at `/opt/workflow_edit` and is
  linked at `/node_modules`. Resolution from `/workspace` (agent) and
  `/tmp/workflow` (evaluator) walks up to it, so no trial installs anything and
  no candidate tree ever contains `node_modules` or a link to it.

## Trial envelope revision 1

The three wire-contract copies (bridge protocol, Assay protocol, shared fixture)
advance together to `assay-pier-trial/0.2.0`. The exact revised field set is:

- `TrialRequest.schema_version` is the new closed version literal.
- `TrialRequest.network_policy` is the closed literal
  `egress-openrouter-only | egress-lan-host-port | toolchain-only`.
- `TrialRequest.egress_host` (an RFC1918 IPv4 address) and `egress_port` (1–65535)
  are present together only for the LAN posture.
- `TrialLimits.storage_mb`, `memory_mb`, and `pids` retain their integer wire
  fields. Storage now bounds a host-visible, quota-backed `/scratch` bind mount;
  memory is an independent cgroup ceiling and must exceed storage.
- `EffectiveEnforcement` adds `root_read_only`, `scratch_mount_kind`, and
  `scratch_quota_mb`. Its existing `storage_limit_mb` is the observed quota,
  and `network_policy` reports the inspected Docker network posture.

## Packaging and fixture identity

- **Arm-bound limits:** Each authorized Pier worker configuration records the
  maximum repository file count and byte count. Dispatch passes these values
  explicitly to the package builder. The wf-13 arm authorizes 200 files and
  1,000,000 bytes; the smoke-edit repository is 62 files and 348,936 bytes.
- **Package layout:** The repository agent edits `/workspace` in place, so its
  package (`package_layout: repository-agent`, recorded in the worker
  configuration) carries the instruction and repository only: no
  `/submission/worktree` text and no `submission/CONTRACT.md`. The DRY layout
  is the unrecorded default, so configurations pinned before it keep their bytes.
- **Containment audit:** Six named synthetic markers cover private
  documentation, transcripts, credentials, other arms, hidden tests, and
  reference solutions. The final package gate rejects a planted marker with
  its category named and confines paths to the sealed mount allowlist.
- **Fixture manifest:** The versioned `assay.fixture_manifest.FixtureManifest`
  is exported as a schema. Hidden tests, reference and negative patches, and
  the rubric are SHA-256 references only. The fixture identity includes the
  observed image digest and the Smithers `routing_config.yaml` digest.
  `qualify.fixture_manifest` fills it for the smoke-edit fixture at run time;
  the smoke has no rubric, and says so in the referenced object.

## Smithers dispatch

- **Pinned model identity:** At authorization, read the exact routing file
  bytes and bind their digest, submitted alias, machine, and the backend tag
  selected by that machine's backend into each arm's worker configuration.
  The worker configuration re-reads the routing file, so `execute_plan`'s
  configuration check before every cell refuses a routing change, and each
  turn also compares its client against the identity captured at
  authorization.
- **Worker attestation:** Smithers 9e305b6's `JobResponse` carries neither the
  resolved tag nor token usage. The completed task on the pinned machine's
  worker (`GET <machine>:8901/tasks/<job>`) carries both in `usage`: its
  `model` is the tag the worker ran and must equal the authorized tag
  (`ResolvedTagIdentityMismatch` otherwise), and missing usage fails the turn
  as `UsageUnavailable` instead of becoming zero tokens. Reading the task from
  the pinned machine's own worker is also the machine check that the job ran
  there.
- **One job per turn:** Every agent turn is one Smithers job keyed
  `<cell key>:t<turn>`, where the cell key is derived from the run label and
  cell id. A re-dispatch after a lost response repeats the same body and key
  and gets the same job. Model-call retries are zero; Smithers' own dispatch
  retries are permitted because they re-offer a slot, not re-run inference.
  Run one dispatch process against one persistent Smithers database for the
  whole run; a database reset or a second database invalidates the key.
- **Clock:** A cell's 900-second budget starts at bridge entry, before its
  first Smithers job, and is enforced by the loop between turns and as every
  tool's timeout. It therefore charges per-turn queue latency to the cell,
  which spends budget rather than extending it; the run wakes mcbain first so
  queue latency is small, and SMOKE.md reports it per turn. Smithers'
  `completed_at - started_at` is still recorded per turn as time from worker
  acceptance. A turn already in flight when the budget expires is cancelled
  on the client side; the job finishes on the worker.
- **Dispatch accounting:** Smithers reports no billing, so a local cell's cost
  coverage is `unavailable`, with the worker-attested token counts carried as
  usage. A cell that ended in a typed failure is `uncertain`; its token counts
  remain in its retained trajectory.

## Repository agent

- **Topology:** The loop runs on the host. Model calls never enter the
  sandbox; tool calls run in a fresh container per cell with no network,
  a read-only root, all capabilities dropped, uid 1000, and Docker tmpfs
  mounts for `/workspace` (256 MiB), `/cache` (256 MiB) and `/tmp` (256 MiB)
  under a 1,536 MiB memory ceiling, 128 PIDs and one CPU. The container
  posture is `toolchain-only`; the LAN-egress posture is not used.
- **Storage:** Docker tmpfs quotas are the declared storage enforcement for the
  local population. The ext4 loop quota (`QuotaCellStorage`) needs passwordless
  `sudo mount` on the dispatch host and is not qualified. tmpfs pages are
  charged to the memory cgroup, so memory is sized above the writable total;
  a full mount surfaces as ENOSPC, and a submission with under 1 MiB free on a
  mount is `storage_exhausted`. Any OOM kill in the cell is `memory_limit`.
  The captured tree is checked before these resource causes, so a full
  `/workspace` is reported as `oversized_artifact` (its own file and total
  limits are far below the 256 MiB mount); `storage_exhausted` is reached
  through `/cache`, which is never captured. `/tmp` free space is not
  observed: a full `/tmp` reaches the model only as ENOSPC from its tools.
- **Capture:** `docker cp` silently returns nothing from a tmpfs mount, so the
  final tree is streamed out with `tar` and extracted as regular files only;
  any link or special file is a typed rejection. (The wf-12 qualification's
  capture used `docker cp` and could not have observed an edit.)
- **Scope:** A submission may change `src/` and `tests/visible/` only. Any
  change to a dependency manifest or test configuration (at any depth, even
  beneath `src/` or `tests/visible/`) or to any other test is
  `tampering`; any other stray path is `out_of_scope_edit`. The rejected tree
  is retained as evidence.
- **Model mistakes are the model's:** A malformed or unknown tool call is
  returned to the model as a tool error. A command that outlives its timeout
  has every process in the container but PID 1 killed and the timeout is
  returned to the model. Only a turn with no tool call, a cut-off turn, or the
  turn limit ends the cell, as `no_submission`, with the work the model left
  behind retained as `stopped/candidate.patch`.

## Correctness evaluation

- **bun mode:** The evaluator's `bun` toolchain typechecks the candidate tree
  alone (`tsc --noEmit -p tsconfig.json`), then bundles every production
  module (`bun build --target=bun`) as the build check, and only then copies
  the frozen tests in, so a hidden test can never fail the candidate's own
  typecheck. Group commands must start with the toolchain's runner. Toolchain
  versions are settings checked inside the sandbox.
- **Frozen visible tests:** The visible regression group is the baseline's own
  `tests/visible/` files, restored over the candidate's copies and run by
  name, so editing or adding a visible test cannot change its regression
  verdict.

## wf-13 qualification

- **What it supersedes:** The wf-12 smoke ran a task with no edit, two model
  requests a cell, and a capture that could not see edits, so it measured no
  token envelope and could only report a 0% failure rate. Its fixture, script,
  and SMOKE.md are removed; its subject id stays refused.
- **Fixture:** `fixtures/smoke-edit`, a 62-file slice of oakridge-dbos at the
  proposed first pin with a four-module task off every Part 2 anchor. Its
  README records provenance, exclusions, and adaptations.
- **Path:** The smoke is an authorized 0.3.0 plan run by `execute_plan`
  through `PierAdapter`, not a direct bridge dispatch. Probes use the same
  path with scripted, model-free turns.
- **Evidence:** Every number in SMOKE.md is recomputed by `publish.py` from the
  committed `evidence/wf13/*.json.gz` files; a test fails if SMOKE.md drifts
  from them.
- **Bounds:** The served local context is 32,768 tokens, so prompt plus output
  must stay under it: an 8,192-token output cap leaves 24,576 prompt tokens,
  and the 81,920-byte conversation cap (98,304 bytes with tools) keeps the
  prompt under that at any ratio above 3.33 bytes per token. The smoke's
  smallest observed ratio was 4.15 and its largest prompt 19,543 tokens, so
  the conversation cap, not the context, is what binds: it dropped old tool
  exchanges 37 times and no request was refused. Two turns reached the
  8,192-token output cap and ended their cells as `no_submission`; the next
  largest completion was 5,966 tokens. The loop does not retain the text of
  a cut-off turn, so whether those were runaway generations or legitimate
  long writes is not recorded; retaining it changes the bridge source and
  therefore the image, and is left to the next image revision. SMOKE.md
  checks each bound against its observed maximum.
- **Routing drift during the smoke:** The smoke process started before the
  live worker configuration and the per-turn authorization check were added,
  so its drift protection was the factory's per-turn re-read alone. The
  worker-attested model is identical on every one of its turns, and
  `routing_config.yaml` was not changed during the run.
- **Correctness result:** 0 of 20 cells were correct. Every graded candidate
  that typechecked failed the same pinned regression test: each applied the
  absolute-pointer rule to every `context` binding, where the task restricts
  only bindings that declare a default. The reference patch passes that test,
  so this is the model's miss and the evaluator's discrimination working, not
  a fixture defect. The smoke qualifies the envelope and the path; it was
  never meant to estimate an arm's success rate.
- **Failure diagnosis:** The evaluator keeps no test output, by design (it
  returns a verdict and one cause per group). `qualify diagnose` replays each
  failed group in the same image, network-less and read-only, and records only
  failing test names or the first typecheck errors as `diagnosis.json.gz`. It
  never re-grades.

## Part 2a — fixture manifest 0.2.0 and multi-arm wiring (Phase A items 7, 8)

- **One document, task records inside it:** `assay-fixture-manifest/0.2.0`
  (`FixtureManifestV2`) is one checkpoint-level manifest with a `tasks` tuple
  of `FixtureTask` records, one per subject, sorted by subject id. A single
  document gives one `fixture_identity` for the whole population, and that
  identity is what the evaluator configuration and therefore the authorized
  plan bind. Adding or changing a task is a new fixture version, which is
  right because the population is frozen before the full plan.
  `task_record_digest` still digests one record on its own, and each
  subject's payload binds it. Two separate documents would need a second
  identity and a cross-reference that could drift.
- **Dose arms are fixed in the core model:** `DoseArm` is the closed literal
  `mess-00 | mess-low | mess-mid | mess-high`. `FixtureTask.arms` must have
  exactly those four keys, and the exported schema enforces the same through
  `propertyNames` and `minProperties`. A test checks that it equals
  `arms.ARM_IDS`. Each arm records its tree digest, its own reference patch,
  its negative patches, and four typed qualification results
  (`baseline_passes`, `feature_fails`, `reference_passes`,
  `equivalence_passes`). Each result is an observed outcome
  (`passed | failed | unavailable`) plus the digest of its retained record.
  The field name states the expected outcome. A manifest can record a failed
  qualification, which keeps the record honest during Phase B, but
  `study.check_fixture` refuses to plan a study unless every arm of every
  task qualified (spec 6: no paid runs until everything qualifies). The four
  arm trees must have distinct digests.
- **Site span unit:** A span is a 1-based, inclusive line range in the
  `mess-00` tree. The treatment unit is a whole calling function, so line
  granularity is exact enough, and a line range can be read with the ranged
  `read_file` and against a diff. Byte offsets are not human-auditable.
  `mess-00` coordinates are the only ones that are stable: an inline copy
  shifts every later line in a dosed arm, and each arm's tree digest pins the
  rest. Sites in one file must not overlap and must name different functions
  (`symbol`).
- **Dose membership is explicit and validated against rank:** Each site lists
  the arms in which it is inline (never `mess-00`), in dose order, and the
  list must be upward closed (a `mess-low` site is in mid and high), which
  gives low ⊂ mid ⊂ high. Ranks are exactly 1..N. Arm k must dose exactly the
  `dose_count(k, N)` lowest-ranked sites (1, ceil(N/2), N). Membership is
  therefore fully implied by rank, but it is stored anyway so the published
  record states the positions without needing the rule to read it, and
  validation catches any disagreement. N (`treatment_site_count`) must be at
  least 4 (spec 5.1) and must equal the number of sites.
- **Removed imports belong to a site and its arms:** An import shared by
  several sites in one file is removed only once all of them are inline. So a
  `RemovedImport` is attributed to the site whose dosing removes it and lists
  exactly the arms where it is gone. Those arms must be inside the site's
  membership and upward closed. Comment corrections are line spans in the
  site's file (in `mess-00` coordinates) with a reason, and they apply
  wherever the site is dosed. The canonical owner is never edited, so a
  correction never lands outside the site's file.
- **Test groups by name:** `visible_tests` and `hidden_tests` are
  `(name, digest)` pairs whose names are unique across both and whose digests
  are distinct. The digest is the store ref of the frozen `WorkflowTestGroup`.
  The evaluator looks each group up by name and refuses a stored group whose
  own name or `restores` flag disagrees.
- **Routing digest required but nullable:** `routing_config_digest` is
  `Sha256Ref | null` and has no default. A hosted fixture states `null`
  explicitly, so forgetting to bind a local routing file cannot be confused
  with "hosted". Identity changes with the image digest and with the routing
  digest, whether set or null.
- **0.1.0 untouched:** `FixtureManifest` and
  `schemas/assay-fixture-manifest.schema.json` are byte-identical, so the
  smoke manifest and readers pinned to that document keep validating. 0.2.0
  is exported beside it as `assay-fixture-manifest-v0.2.schema.json`.
  `parse_fixture_manifest` selects the model from `schema_version`. A
  root-level `oneOf` like the execution plan's would have changed the
  existing document, so the unversioned name stays 0.1.0.
- **Per-cell evaluator (spec 8.1):** `evaluation.CellEvaluator` takes subject
  and arm from the cell id, the baseline from `input_value` (the realization
  `execute_plan` read from the cell's own `realization_ref`, the same bytes
  the worker was given), and the submission's baseline digest from the
  worker's `result.json` (`worker_candidate`). It refuses
  `realization_digest_mismatch` when the given tree is not the manifest's
  tree for that arm, and `baseline_digest_mismatch` when the worker's
  recorded baseline is not that tree. It also refuses an output whose
  `cell_id` is another cell's. The smoke's `CorrectnessEvaluator` now reads
  the baseline digest and the baseline the same way, which removes the
  fabricated digest that made `evaluate_candidate`'s check vacuous. Only its
  0.1.0 hidden refs stay positional. A positional slip still surfaces as
  `invalid_hidden_tests`, because each stored group carries its own name.
- **Study path beside the smoke path:** `study.plan_study` / `prepare_study`
  build four realizations per subject. Every arm carries
  `assay_execution_schedule: subject-rotated-v1`, and `validate_worker_grid`
  runs on the compiled plan's cells inside `compile_workflow_plan`, before
  the plan bytes exist to authorize. `qualify.prepare` (smoke and probes)
  shares that plan compiler without the grid check, because its one-arm grid
  over a qualification subject is refused by design. `qualify.run`
  dispatches every snapshot arm to the same worker. One worker serves all
  four arms because the arm differs only in the realization it is given.
- **Fixture checks before planning:** `study.check_fixture` requires the
  manifest's image digest to match the run's image, its routing digest to
  match the run's routing digest (`null` for hosted), each subject to have
  exactly one tree per arm matching its arm digest, every arm to have
  qualified, and visible tests to be identical across arms (spec 5.1: exposed
  tests are fixed).
- **Not here:** No real 2a fixture is built (Phase B). The offline test
  `tests/test_workflow_edit_study.py` uses a synthetic subject with N = 4 and
  four tiny trees, runs a 1 × 4 × 4 grid through `execute_plan` with a
  scripted worker and a recording runner, and covers a worker that reports
  the wrong baseline. Per-arm file sizes for the envelope check (spec 5.1)
  are not yet a manifest field.
