# Pier integration: qualification, preparation, execution, and recovery

Pier is the third-party (`datacurve-pier`) agent-execution provider Assay drives
through the isolated `integrations/pier` bridge project (see
`integrations/pier/README.md`). This document covers the operational path end
to end -- preparation through recovery -- without performing a paid run. No
command below spends money or requires an OpenRouter credential unless its
section says so explicitly.

## Clean build, both projects

The root project and the isolated `integrations/pier` bridge each carry their
own lock and are checked independently -- this is the exact, reproducible
sequence `.github/workflows/ci.yml`'s `pier-qualification` job runs, in this
order, from a clean checkout:

```sh
uv sync --locked --extra review --extra legacy
uv run ruff check integrations/pier
MYPYPATH=integrations/pier/src uv run mypy integrations/pier/scripts/qualify_local.py
uv run pytest -q tests/test_pier_acceptance.py

cd integrations/pier
uv sync --locked --group dev
uv run mypy src
uv run pytest -q
cd -
```

The first block lints/type-checks/tests the qualification script and the
credential-free acceptance matrix against the root project's own locked
environment (root `ruff`/`mypy` already cover `src`/`tests` themselves --
see `README.md`'s "Install and check"). The second block syncs, type-checks,
and runs the bridge's full pytest suite (protocol, provider, host-driver,
container-lifecycle, and trial-lifecycle tests) against the bridge's own
separate lock -- no shared virtualenv, no shared dependency resolution. Every
step above is credential-free; the container-lifecycle and trial-lifecycle
tests skip themselves cleanly when no local Docker daemon is reachable
rather than failing.

## Qualify the local runtime first

Every paid Pier profile requires a real, recorded `QualificationInventory`
(`assay.runtime_inventory`). `integrations/pier/scripts/qualify_local.py`
produces one, but only after every probe it runs has passed:

```sh
uv run --extra review --extra legacy python integrations/pier/scripts/qualify_local.py
```

In order, it checks: the bridge's exact pinned revisions, lock digest
(`integrations/pier/uv.lock`), and locally built image digest, each compared
against the exact identity `assay.investigations.pier_experiment` requires
for paid execution -- not merely recorded and trusted; that a real container
built from that image runs under the exact same `TrialLimits` (cpu, memory,
pids, and a size-capped `/scratch` tmpfs) a real paid trial dispatches under,
observes those limits actually enforced (not merely declared), tears down
cleanly, and leaves zero stray `assay-pier-` containers (the trial-lifecycle,
effective-Docker-controls, teardown, and orphan checks); that a small,
dedicated storage cap is a real ENOSPC ceiling, proven by a deliberate
overflow write that must fail (the storage-enforcement check); that the
image needs no network to start (the no-reinstall check, and that a single
bridge lifecycle refuses a second trial request); the guarded OpenRouter
route's fail-closed behavior against a fake HTTP transport, at the exact
route paid execution is configured to call (no real network call, no
credential); and the core-side artifact round trip, accounting, and
cancellation-cleanup behavior against a fake bridge client.

Because Docker server version and the locally built image's digest are the
two measured identities that are legitimately host/build-dependent
(`integrations/pier/README.md` flags the image digest as explicitly
non-reproducible across machines), qualification can fail here even on a
correctly configured machine simply because it is not the one reference
machine `EXPECTED_DOCKER_VERSION`/`PIER_BRIDGE_IMAGE_DIGEST` were pinned
from -- this is a real, working gate, not a bug in the script.

The first probe that fails stops the run with a nonzero exit and no inventory
is written -- there is no partial or best-effort qualification, and every
probe category has an independent negative test in
`tests/test_pier_acceptance.py` proving it specifically leaves no inventory.
On success it publishes the inventory into a local `ObjectStore`
(`--output-dir`, default `.assay-pier-qualification`) and prints its `sha256:`
ref:

```
qualified: sha256:...
```

That ref is the `inventory_ref` every paid profile below requires. It never
touches `OPENROUTER_API_KEY` and never dials out; `tests/test_pier_acceptance.py`
asserts both, and re-runs the whole script end to end whenever a local Docker
daemon is reachable -- see that module for the full credential-free acceptance
matrix CI runs on every pull request.

## Preparation never spends anything

`prepare_pier_smoke`/`prepare_pier_qualification`/`prepare_pier_full`
(`assay.investigations.pier_experiment`) compile and publish a plan without
touching Docker, the network, or a real qualification -- an omitted
`inventory_ref` falls back to a synthetic, always-valid default built from the
same pinned identity constants a real qualification measures, safe because
preparation is never authorization to spend:

```python
from assay.investigations.correctness import DockerPythonRunner
from assay.investigations.pier_experiment import prepare_pier_smoke
from assay.store import ObjectStore

store = ObjectStore(".assay/pier-smoke-v1")
prepared = prepare_pier_smoke(store, runner=DockerPythonRunner())
print(prepared)  # PierExperimentPrepared(snapshot_ref=..., plan_ref=..., cells=4, evaluations=8)
```

Replace `prepare_pier_smoke` with `prepare_pier_qualification` (16 cells) or
`prepare_pier_full` (48 cells) for the other two profiles. Inspect the plan and
its complete reference closure before proceeding, exactly as for the DRY and
realistic-pilot investigations (see `docs/dry-experiment.md`).

## Three distinct paid decisions -- never substitutable for one another

Paid dispatch requires four things at once, each an independent, explicit
operator decision, enforced by `run_pier_*` itself (`assay.investigations.pier_experiment`)
before a single byte of the plan is read or the bridge client's `create` is
ever invoked:

1. `allow_paid=True` on the specific `run_pier_*` call for the specific
   profile being authorized -- approving `smoke` never authorizes
   `qualification` or `full`;
2. `ASSAY_ALLOW_PAID_PIER=1` in the process environment -- a distinct,
   env-level approval a caller's own `allow_paid=True` can never itself
   satisfy, so a script that always passes `allow_paid=True` still cannot
   dispatch for real without a separate operator decision on the machine
   actually running it;
3. a real, nonblank `OPENROUTER_API_KEY` in the process environment, since
   the bridge's guarded route (`GuardedOpenRouterClient`) needs one to place
   its single call per trial;
4. a real `inventory_ref` from a qualification `qualify_local.py` actually
   ran on this machine -- the synthetic preparation default is never
   accepted here, and an omitted ref is a hard failure.

`tests/test_pier_acceptance.py` proves each of the four independently, for
every profile: a paid call missing just that one gate rejects with a message
naming that gate specifically, *before* the bridge client's `create` is ever
invoked -- a poison bridge that would fail the test outright if dispatch ever
reached it. Ordinary CI sets neither environment variable, so none of the
sections below ever run for real there; a `@pytest.mark.paid` test documents
the same two-env-variable requirement and is skipped, never dispatched,
unless an operator has separately set both.

### One-subject paid smoke -- $2.88 ceiling

```python
from assay.investigations.pier_experiment import run_pier_smoke

result = await run_pier_smoke(
    store,
    plan_ref=approved_plan_ref,
    authorization=approved_plan_ref,
    bridge=your_pier_bridge_client,
    allow_paid=True,
    inventory_ref=qualified_inventory_ref,
    export_destination=Path(".assay/pier-smoke-v1-run-1-bundles"),
)
```

Four cells (one subject, two arms, two worker repeats), $1.44 per arm. This is
an operational check of the whole path -- routing, packaging, artifact
evidence, reporting -- not evidence about the treatment itself.

### Four-task paid qualification -- $11.52 ceiling

Same call shape against `run_pier_qualification`: 16 cells across the four
`REALISTIC_PILOT_FIXTURES` tasks, $5.76 per arm. Validates repository
navigation and sandboxed package execution across a larger, more realistic
grid before committing to the full study.

### Full paid study execution -- $34.56 ceiling

Same call shape against `run_pier_full`: 48 cells across all twelve
`EXPERIMENT_TASKS`, $17.28 per arm. Requires its own independent plan
inspection and `allow_paid=True` decision -- passing smoke or qualification is
not a substitute, and `_revalidate_before_dispatch` re-checks the plan's own
runtime configuration and cost ceilings against the live binding immediately
before dispatch, not merely once at preparation time.

## Bundle verification

Every `run_pier_*` call given an `export_destination` (a new, not-yet-existing
directory) writes independent `abstraction/` and `correctness/` report
bundles and verifies both before returning -- a nonzero `verify_bundle`
failure count raises rather than returning a result that looks successful.
Re-verify offline at any later point:

```sh
assay verify .assay/pier-smoke-v1-run-1-bundles/abstraction sha256:ABSTRACTION_REPORT_REF
assay verify .assay/pier-smoke-v1-run-1-bundles/correctness sha256:CORRECTNESS_REPORT_REF
```

This needs no network, no installed PAA package, and no Pier credential.

## Inspecting cancellation evidence

An operator-cancelled trial never returns a `WorkerResult` -- the
`asyncio.CancelledError` propagates -- but `PierAdapter.run_cell` still
publishes a durable `assay-pier-cancellation-trace/0.1.0` object into the
store before it does, recording the coordinate, whether teardown was
independently confirmed clean (`cleanup_incomplete`), and refs to whatever
partial artifacts existed. Find it by scanning the store for that
`schema_version`, the same way `qualify_local.py`'s own cancellation probe
checks its fake bridge scenario. `cleanup_incomplete: true` means teardown was
never confirmed complete -- treat any resources it might have left as
possibly still live, not as safely gone.

## Orphan cleanup checks

After any real trial (paid or the qualification script's own local one),
confirm no `assay-pier-*` container was left behind:

```sh
docker ps -a --filter 'name=assay-pier-' --format '{{.Names}}'
```

A nonempty result is an unconfirmed leak, not a false alarm -- force-remove it
(`docker rm -f <name>`) and treat that trial's accounting as `uncertain` (see
below) even if the trial's own `WorkerResult` reported success.

## Operational outcomes to recognize, not guess at

Several process states are first-class, expected outcomes here, not edge
cases to special-case away in a report:

- **A worker exception during dispatch.** Its exception type and message are
  captured in the resulting `WorkerFailure`, and `Accounting(coverage=
  "uncertain")` is recorded -- the trial was dispatched, so its cost is
  unknown, never silently zero.
- **mini's own embedded `exit_status`.** `mini_exit_status_from_result_bytes`
  reads it from the `result` artifact independently of Pier's own trial
  `status`; `bridge_reports_failure` requires both signals to agree the trial
  succeeded, so a bridge claiming success with a failing embedded exit status
  is still a failure.
- **Missing or invalid required artifact evidence.** `has_required_success_evidence`
  and `verify_artifact_bytes` gate every success on all five required kinds
  (`raw_trajectory`, `candidate`, `result`, `configuration`, `manifest`) being
  present, correctly sized, checksum-matched, and (where declared) valid
  UTF-8/JSON -- a plausible-looking manifest with one wrong byte is a
  `ManifestRejected` failure, not a warning.
- **Uncertain billing.** `Accounting(coverage="uncertain")` versus `"measured"`
  is the distinction between "we don't know what this cost" and "we observed
  the cost" -- never collapse the former into a reported zero.
- **Unconfirmed cleanup.** `teardown_completed` plus `containers_remaining`/
  `child_processes_remaining` are what confirms a clean teardown; anything
  else is `cleanup_incomplete`, whether or not the trial itself succeeded.
- **A persisted incomplete manifest.** `RunManifest.status == "incomplete"`
  with a nonempty `missing_coordinates` is expected, inspectable output for a
  halted or partially failed run -- it remains reachable through `RunFailed`
  and is never silently promoted to a complete run or used to build a report.
- **Missing runtime coordinates.** A `RunManifest` missing a worker or
  evaluator coordinate it should have recorded is named explicitly in
  `missing_coordinates` (`worker:<cell>` / `evaluator:<evaluation>`), so a
  recovery pass knows exactly what evidence is absent rather than inferring it
  from a manifest's overall shape.

## Final rehearsal

Before relying on any of the above for a real decision, rehearse it end to
end in a clean environment with no Jig extra installed (mirroring
`tests/test_optional_jig.py`'s no-Jig wheel acceptance): verify the fixed
legacy bundle recorded in this checkout, then generate and verify a fresh
Pier bundle from a local qualification and a `smoke` preparation, and inspect
every model-visible and exported artifact for a hidden, reference, or
alternate-arm sentinel -- none of the sections above should leak arm identity,
task family, or evaluator hints into anything the model or an exported bundle
can see.
