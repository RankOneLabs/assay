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

## Trial envelope revision 2

The same three copies then advanced to `assay-pier-trial/0.3.0` (commit
`1898834`), the version the code carries today. Revision 1's request, limit and
enforcement fields are unchanged. The bridge's `TrialResult.outcome` became a
union discriminated on `kind`: `candidate` (patch, tree and baseline tree
digests), `candidate_failure` or `infrastructure_failure`, each failure with a
closed cause. This is the trial envelope; `assay-execution-plan/0.3.0` is an
unrelated plan version.

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

## Part 2a — operator decisions (2026-10-15)

Copied from section 12.1 of the Part 2 spec, which lives outside this
repository; "spec" below means that document.

- **Split:** Part 2 is 2a, a thin slice through one task, then 2b, the study.
  2b is re-planned against 2a's report before it is built (spec 0.4).
- **Populations:** Local and hosted are both in scope, each its own plan,
  authorization and ceiling, never pooled. The hosted path is built in
  Phase A. The hosted model is `qwen/qwen3.5-397b-a17b`.
- **Local model:** Qwen3.6-27B (FP8) on mcbain, served before the
  requalification smoke. Qwen2.5-Coder-32B remains the qualified fallback
  (spec 7.1).
- **2a task:** JSON pointer strictness, owned by `readJsonPointer`, dosed per
  calling function with N = 5 (spec 4.2). The PR-identity task is the
  alternate.
- **Outcome classification:** As in spec 8.0. Model failures are scored
  outcomes, not missing data. Infrastructure failures get one replacement
  attempt.
- **v1 slice:** Keeps the pure layers and excludes `storage/`, `http/`,
  `adapters/`, `workflows/` and the composition root. Tasks observable only
  through storage are deferred (spec 3.1).
- **Agent tools:** Ranged `read_file`, exact-match `replace_in_file`, and
  retention of cut-off turn text, in a new image and therefore a new fixture
  version (spec 7.2).
- **Review:** 2a has single-reviewer operator review, only where the automated
  checks cannot decide (spec 8.2). In 2b, review records are a separate review
  set bound to one run manifest, and reviewer identity is operator-held and
  outside the closure. 2b tie-breaking is a report-time setting, defaulting to
  `unavailable`, with `lower`/`higher` bounds and no reviewer-precedence rule.
- **Hosted smoke:** Worth its 4 paid cells.
- **Pilot (2b):** 4 subjects × 4 doses × 2 repeats. The capability gate is at
  least one `correct` cell in at least two pilot subjects.
- **Hosted admission:** Per turn. Run ceilings are $2 for the smoke, $5 for the
  optional thin-slice run and $10 for the pilot. Venice is excluded from
  routing (spec 10). Each paid plan is still its own spending decision.
- **Fixtures:** Hand-assembled and committed. Dose arms derive from the
  committed fixture, and dependencies arrive through the runtime image.
- **Bounds:** Part 1's measured bounds (SMOKE.md) replace the draft's
  placeholders (spec 7.2).
- **Cell clock:** The 900 s budget runs from bridge entry, on condition that
  Phase A stops a cancelled turn from occupying the GPU into the next cell
  (spec 0.2 item 6, Phase A item 2).
- **Component mapping:** Lives in `experiments/workflow_edit/`.
  `oakridge_history` is on `main`; `oakridge_history_analysis` does not exist.
- **Unpriced local cost:** A zero-cost local arm is reported as unpriced,
  never as cheaper.
- **Still open (spec 12.2):** Whether to run the optional hosted thin-slice run
  (after the hosted smoke); the hosted model for 2b (in the 2a report); (2b)
  the two reviewers and the adjudicator. Qwen3.6-27B's served context and
  thinking mode are settled below.

### Qwen3.6-27B on mcbain (Phase A item 0)

- **Served:** Smithers PR #52 (RankOneLabs/smithers), merged and deployed at
  `6086d5f`, adds fleet alias `qwen3.6-27b` on mcbain with backend tag
  `/home/steve/models/Qwen3.6-27B-FP8` under vLLM 0.22.1. Its own flags:
  `--max-model-len 131072`, `--max-num-seqs 16`, `--language-model-only`,
  `--tool-call-parser qwen3_coder`, `--reasoning-parser qwen3`, and
  `--default-chat-template-kwargs '{"enable_thinking": false}'`. Every other
  model keeps its exact command line, including the 32,768 context.
- **Context:** vLLM reports 12.1 GiB of KV cache, 193,158 tokens, so 131,072,
  the larger of the two candidates in spec 7.1, fits beside the weights.
  `--max-num-seqs 16` is what makes it fit: the linear-attention layers
  reserve state per sequence slot, and vLLM's default of 256 slots ran out of
  memory.
- **Thinking:** Off by server default. A request can still turn it on, so the
  authorized configuration records it explicitly when the route lands.
- **Tool calls and attestation:** A Smithers job with `tool_choice: "required"`
  returned a structured tool call, and the worker task attested model
  `/home/steve/models/Qwen3.6-27B-FP8` with usage.
- **Speed:** 39 tok/s decode, measured by hand (Qwen2.5-Coder-AWQ: 48.7 median
  in SMOKE.md). Worker cold start 68 s; the manual launch took 144 s.
- **Not yet switched:** Assay's route literal
  (`assay_pier_bridge.protocol.ModelRoute`, with `workflow_edit.bridge.LOCAL_ROUTE`
  and `qualify.MODEL_ALIAS`) still admits only `qwen-coder-32b`. Switching is a
  later Phase A cohort, together with the hosted path's model route. The
  conversation and request caps are re-derived from the served context in the
  requalification smoke (spec 7.1).
- **Re-binding:** PR #52 changed `routing_config.yaml`, so its digest changed.
  Every authorized worker configuration and fixture identity binds that
  digest, so each re-binds, including `qwen-coder-32b` configurations whose tag
  did not change; `execute_plan` refuses a plan authorized against the old
  digest. SMOKE.md's fixture identity is for the old digest.

### Backend identity (spec 0.2 item 7)

- **Inferred, not read:** Part 1 asked that a job reporting a different
  machine, model or backend than declared fail its cell. Machine and model are
  checked against reported fields; the backend is not, because no Smithers
  field reports it. Neither `JobResponse` nor the worker task's
  `usage` (`TaskUsage`: `model`, token counts, duration) names a backend.
  `_routing_identity` (`src/assay/adapters/smithers.py:30-55`) infers it from
  the routing file: machine → that machine's `backend` (default `ollama`) →
  the alias's `backend_tags[backend]` (or `ollama_tag`). The routing digest
  pins that mapping, and the worker-attested `usage.model` must equal the
  selected tag (`smithers.py:323-327`).
- **Why that suffices today:** The two backends' tags are distinct string
  forms. vLLM tags are absolute weight paths (`/home/steve/models/...`);
  Ollama tags are `name:tag` (`qwen2.5:72b-instruct-q8_0`). A tag match
  therefore also identifies the backend.
- **When it fails:** If two backends could carry the same tag string — one
  alias with the same tag under both `backend_tags`, a vLLM model served under
  an Ollama-form name, or a worker that routes a tag to a backend other than
  the one its routing entry names — a matching tag no longer implies the
  authorized backend. Then Smithers must attest the backend (a field on the
  worker task's usage), and the client must compare the (backend, tag) pair
  against the authorized pair instead of the tag alone.

## Part 2a — bridge loop (Phase A items 1, 3, 5)

These change the bridge source, the system prompt, and `tools_sha256`, so they
are a new image and a new fixture identity. Nothing here was run against
Smithers; the Phase A requalification smoke qualifies them.

- **Patch capture isolation:** Capture runs Git with `GIT_CONFIG_GLOBAL` set
  to `/dev/null`, `GIT_CONFIG_NOSYSTEM=1`, every inherited `GIT_*` variable
  removed, `core.excludesFile=/dev/null`, and an empty init template. Both
  adds use `-f`, so a `.gitignore` in the tree is captured content, never a
  filter. After the adds, the index must hold exactly the observed paths;
  otherwise capture stops as `patch_capture_incomplete` (a capture crash,
  so infrastructure under section 8.0), never a short patch.
- **Reserved Git paths:** A path component Git treats as its own metadata is
  `out_of_scope_edit` at any depth. That means `.git` in any ASCII case, or
  a spelling Git's default `verify_path` refuses as one (`git~1`, trailing
  dots or spaces, a `:` stream suffix). Git either drops such a path from
  the index without an error (`src/x/.git`) or fails the whole add, so no
  patch could carry it. It is not `tampering`. That cause is kept for edits
  that change what the evaluator runs: manifests, test configuration, and
  tests. A top-level `.git` was already `out_of_scope_edit` in Part 1.
  Names that only resemble it (`.gitx`, `git~2`) are captured normally.
- **`agent_deadline` is a model failure:** When the cell budget runs out
  inside the loop (between turns, during a turn, or as a tool's timeout), the
  trial ends as a candidate failure with the new cause `agent_deadline`.
  `harness_deadline` remains infrastructure. It covers a budget spent before
  the trial handle runs and any other client's `TrialTimeoutError`.
- **Trial envelope revision 2:** Adding `agent_deadline` to the closed
  `CandidateCause` set is a wire change. The three copies (bridge protocol,
  Assay protocol, shared fixture) advance together to
  `assay-pier-trial/0.4.0`. No other field changes. The copies had been at
  `0.3.0` since discriminated outcomes, which also changed only closed
  literals. Revision 1 above names `0.2.0`, the version it introduced.
- **`memory_limit` rule:** After every tool call that ran a command (a timed-out
  one included), the loop reads the cgroup's `memory.events` `oom_kill`
  count. Any increase is recorded as an `oom_kill` event (turn, tool, kills,
  total). It is recovered: the kill happened inside a result the model saw.
  The final check is `capture_workspace`'s observation at submission. The
  submission is `memory_limit` exactly when that count exceeds the count
  after the last tool result, which means the cgroup hit its ceiling after the
  model last looked: during its final turn, through a process it left
  running, or during the check itself. `memory.current` is not used, because
  page cache makes "at the limit" ambiguous. An OOM kill is the kernel's own
  statement that the ceiling was reached. `cgroup_peaks` records
  `oom_kills_seen_by_tools` beside the final count. This replaces the Repository
  agent rule that any OOM kill in the cell is `memory_limit`. The cost is one
  extra `docker exec` per tool call. Bind-mount sandboxes observe no cgroup
  counters, as before.
- **Submission check order:** At submission the order is: capture, then the
  captured tree's own typed rejections (`regular_tree`), then scope and
  tampering, then the resource causes (`memory_limit`, then
  `storage_exhausted`), then the patch. A tampering submission that also hit
  a resource ceiling is `tampering`.
- **Probes:** The memory probe splits in two. `memory_recovered` is a
  foreground hog killed inside its own tool call, and settles as `candidate`.
  `memory_limit` is a background loop that respawns the hog, with a scripted
  10-second pause before the submission. In a local run against the image,
  three kills landed in that window. The `agent_deadline` probe now expects
  `agent_deadline`. SMOKE.md and the wf-13 evidence are unchanged, because the
  probe table publishes the expectation recorded in the evidence.
- **Tool set and order:** The tools are `read_file`, `write_file`,
  `replace_in_file`, `run_command`, `submit_output`, in that fixed order.
  Their schemas are 1,870 bytes, against the 16,384-byte cap, and a test pins
  both. Optional arguments follow strict-mode convention: a nullable type,
  still listed as required. The loop accepts them absent or `null`.
  Whether vLLM's guided decoding accepts the `["integer", "null"]` type
  is first shown by the requalification smoke.
- **Paged reads:** Lines split on `\n` only, so a line number means the same
  thing to `read_file`, to `replace_in_file`, and to an editor.
  `start_line`/`end_line` are 1-based and inclusive, and `end_line` past the
  end is clamped. A page ends at a whole line, with 256 bytes kept for its
  note. The note names the lines shown, the total, the lines left in the
  requested range, and the next `start_line`. A single line longer than a page
  shows its first bytes and says so. Invalid UTF-8 is decoded with
  replacement, so a read never refuses a file `cat` would have shown.
- **Exact edits:** `replace_in_file` reads and writes bytes untranslated,
  needs UTF-8, refuses an empty `old`, and applies `write_file`'s path rule:
  a canonical relative path that resolves inside `/workspace`. Its script,
  and `read_file`'s, refuse a call with exit status 3 and a one-line reason.
  The loop returns that reason to the model as a `tool_error`. Zero or several
  matches, a missing file, or an escaping path changes nothing and never ends
  the cell.
- **Truncation is visible:** Any other tool output cut at the tool cap ends
  with a note giving the cap and the original size, inside the same cap.
- **Cut-off turns are retained:** A turn whose `finish_reason` is `length`, or
  whose completion reaches the output cap, is recorded as an `output_cut_off`
  event with its text and raw tool calls. This holds whether or not the turn
  ends the cell. Events are never dropped by conversation truncation, so the
  text survives where the replayed messages may not. Truncation still removes
  only whole exchanges (an assistant turn and all its tool results), and a
  test checks every request for orphaned results.
- **Publication of wf-13:** `publish.py` uses the 1,120-byte schema size of the
  four tools the wf-13 image ran, not the current `TOOLS`. That way SMOKE.md
  still reproduces exactly from its committed evidence.

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
