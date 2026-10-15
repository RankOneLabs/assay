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
