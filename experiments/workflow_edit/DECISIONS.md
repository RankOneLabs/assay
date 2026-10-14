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

Initial storage, memory, and PID numbers are provisional; replace them after
the footprint runs recorded in `experiments/workflow_edit/SMOKE.md` (wf-12).

The wf-12 offline smoke gate passed install, typecheck, and test in a container,
and the harness sealed its observed artifacts. The inspected memory and PID
values are configured ceilings, not peak usage. The Smithers/Pier model gate
and 20-dispatch qualification are outstanding, so the provisional bounds
remain until real replacement measurements exist.

## Packaging and fixture identity

- **Arm-bound limits:** Each authorized Pier worker configuration records the
  maximum repository file count and byte count. Dispatch passes these values
  explicitly to the package builder.
- **Containment audit:** Six named synthetic markers cover private
  documentation, transcripts, credentials, other arms, hidden tests, and
  reference solutions. The final package gate rejects a planted marker with
  its category named and confines paths to the sealed mount allowlist.
- **Fixture manifest:** The versioned `assay.fixture_manifest.FixtureManifest`
  is exported as a schema. Hidden tests, reference and negative patches, and
  the rubric are SHA-256 references only. The fixture identity includes the
  observed image digest and the Smithers `routing_config.yaml` digest.

## Smithers dispatch

- **Pinned model identity:** At authorization, read the exact routing file
  bytes and bind their digest, submitted alias, machine, and the backend tag
  selected by that machine's backend into each arm's worker configuration.
  The client checks the routing file again before accepting a completion.
  Smithers 9e305b6 reports the alias and machine in `JobResponse`, but does
  not report the resolved worker tag; a worker-side tag attestation therefore
  cannot be verified from that response alone. The optional response/result
  tag checks in the client are forward-compatible with a future attesting
  Smithers response, and do not strengthen the current guarantee.
- **Idempotency topology:** Run one dispatch process against one persistent
  SQLite database path for the entire qualification run. Smithers defaults to
  `db_path="smithers.db"`, relative to the dispatch process working directory;
  record its resolved absolute path with the run manifest before dispatch, and retain the
  database between retries. A stable key derived from run ID and cell ID is
  sent with every `JobSubmission`; repeat the same body when retrying a
  dropped response. Exercise this in the live qualification run. A database
  reset or a second process using another database path invalidates the gate.
- **Clock:** Set Smithers `timeout_seconds` to 900. Its `started_at` is written
  when the worker accepts a task. Report `started_at - created_at` as queue
  latency and `completed_at - started_at` as time from acceptance; only the
  latter is charged to the 15-minute cell budget. Smithers writes both
  timestamps as naive wall-clock values on its own host, so their
  *difference* is trustworthy but neither one is an instant this host can
  read: treating `started_at` as UTC silently charges the cell a whole
  timezone offset wherever the dispatch host is not on UTC. The concrete
  workflow delegate therefore re-anchors acceptance locally, as
  `now - time_from_acceptance - poll_interval`, and passes that into
  `BridgeRuntime.run_cell`; no foreign absolute timestamp crosses the
  boundary. The poll interval is subtracted because this host learns of a
  completion only at the poll that observes it: the true completion lies
  somewhere in the preceding interval, so charging the whole of it spends
  the cell's budget rather than extending it. `BridgeRuntime` clamps the
  result so an acceptance point in its own future cannot buy more than the
  authorized limit. The bridge gives the handle an absolute monotonic
  deadline before quota setup, network setup, and container launch; those
  stages consume the same acceptance budget, as does every Docker call
  made after the container exits, so evidence collection cannot overrun
  the budget the trial was authorized with. `TrialHandle.set_deadline` is
  part of the protocol, not an optional method — the budget is not
  re-applied to `limits.timeout_s`, so a handle that ignored it would
  enforce nothing. The guarded host route can only check the deadline
  between steps, at entry and again immediately before its one OpenRouter
  call: that call is bounded by `provider.TIMEOUT_S` and cannot be
  interrupted in flight.
- **Dispatch accounting:** Only the bridge leg of a workflow cell is
  priced. Smithers reports no billing (`billing: unavailable` in the
  pinned worker configuration), so a successful cell carries the bridge
  trial's measured amount under `mixed` coverage, never `measured` — which
  would assert the dispatch leg cost nothing. An attempt that reached the
  bridge but returned no usage is `uncertain`, not zero.
