# Pier qualification runner

This standalone runner covers preparation through recovery. Bridge and adapter
setup remains documented in [`docs/pier-integration.md`](../../docs/pier-integration.md).

## Clean build, both projects

The root project, experiments project, and isolated `integrations/pier` bridge
each carry their own lock and are checked independently -- this is the exact,
reproducible sequence `.github/workflows/ci.yml`'s `pier-qualification` job
runs, in this order, from a clean checkout:

```sh
uv sync --locked --extra review --extra legacy
uv run ruff check integrations/pier
MYPYPATH=integrations/pier/src:experiments uv run mypy integrations/pier/scripts/qualify_local.py
uv run --extra review --extra legacy python integrations/pier/scripts/qualify_local.py --help
cd experiments
uv run --locked pytest -q pier_qualification/tests/test_pier_acceptance.py

cd ../integrations/pier
uv sync --locked --group dev
uv run mypy src
uv run pytest -q
cd -
```

The first block lints and type-checks the qualification script against the root
lock, then tests the credential-free acceptance matrix against the experiments
project's lock (root `ruff`/`mypy` already cover `src`/`tests` themselves -- see
`README.md`'s "Install and check"). The second block syncs, type-checks,
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
against the exact identity `pier_qualification.pier_experiment` requires
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
`pier_qualification/tests/test_pier_acceptance.py` proving it specifically leaves no inventory.
On success it publishes the inventory into a local `ObjectStore`
(`--output-dir`, default `.assay-pier-qualification`) and prints its `sha256:`
ref:

```
qualified: sha256:...
```

That ref is the `inventory_ref` every paid profile below requires. It never
touches `OPENROUTER_API_KEY` and never dials out;
`pier_qualification/tests/test_pier_acceptance.py`
asserts both, and re-runs the whole script end to end whenever a local Docker
daemon is reachable -- see that module for the full credential-free acceptance
matrix CI runs on every pull request.

## Preparation never spends anything

`prepare_pier_smoke`/`prepare_pier_qualification`/`prepare_pier_full`
(`pier_qualification.pier_experiment`) compile and publish a plan without
touching Docker, the network, or a real qualification -- an omitted
`inventory_ref` falls back to a synthetic, always-valid default built from the
same pinned identity constants a real qualification measures, safe because
preparation is never authorization to spend:

```python
from assay.investigations.correctness import DockerPythonRunner
from pier_qualification.pier_experiment import prepare_pier_smoke
from assay.store import ObjectStore

store = ObjectStore(".assay/pier-smoke-v1")
prepared = prepare_pier_smoke(store, runner=DockerPythonRunner())
print(prepared)  # PierExperimentPrepared(snapshot_ref=..., plan_ref=..., cells=4, evaluations=8)
```

Replace `prepare_pier_smoke` with `prepare_pier_qualification` (16 cells) or
`prepare_pier_full` (48 cells) for the other two profiles. Inspect the plan and
its complete reference closure before proceeding, exactly as for the DRY and
realistic-pilot investigations (see `../consistency_pilot/dry-experiment.md`).

## Three distinct paid decisions -- never substitutable for one another

Paid dispatch requires four things at once, each an independent, explicit
operator decision, enforced by `run_pier_*` itself (`pier_qualification.pier_experiment`)
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

`pier_qualification/tests/test_pier_acceptance.py` proves each of the four independently, for
every profile: a paid call missing just that one gate rejects with a message
naming that gate specifically, *before* the bridge client's `create` is ever
invoked -- a poison bridge that would fail the test outright if dispatch ever
reached it. Ordinary CI sets neither environment variable, so none of the
sections below ever run for real there; a `@pytest.mark.paid` test documents
the same two-env-variable requirement and is skipped, never dispatched,
unless an operator has separately set both.

### One-subject paid smoke -- $2.88 ceiling

Exact operator sequence, in order, with a checkpoint after each step:

```sh
export ASSAY_ALLOW_PAID_PIER=1
export OPENROUTER_API_KEY=sk-...   # a real key -- this step spends money
```

```python
from pathlib import Path

from assay.investigations.correctness import DockerPythonRunner
from pier_qualification.pier_experiment import PierExperimentPrepared, prepare_pier_smoke
from assay.store import ObjectStore
from assay.canonical import digest_bytes

store = ObjectStore(".assay/pier-smoke-v1")
prepared = prepare_pier_smoke(store, inventory_ref=qualified_inventory_ref, runner=DockerPythonRunner())
assert isinstance(prepared, PierExperimentPrepared)          # checkpoint: compiled, not yet authorized
assert prepared.cells == 4 and prepared.evaluations == 8     # checkpoint: exact smoke-profile grid

# Read the plan back and inspect it -- authorization below is against these
# exact bytes' digest, never a plan re-derived from the profile's name alone.
plan_bytes = store.read_bytes(prepared.plan_ref)
authorization = digest_bytes(plan_bytes)
```

```python
from pier_qualification.pier_experiment import PierExperimentSucceeded, run_pier_smoke

result = await run_pier_smoke(
    store,
    plan_ref=prepared.plan_ref,
    authorization=authorization,
    bridge=your_pier_bridge_client,
    allow_paid=True,
    inventory_ref=qualified_inventory_ref,
    export_destination=Path(".assay/pier-smoke-v1-run-1-bundles"),
)
assert isinstance(result, PierExperimentSucceeded), result   # checkpoint: dispatched and completed
```

Four cells (one subject, two arms, two worker repeats), $1.44 per arm. This is
an operational check of the whole path -- routing, packaging, artifact
evidence, reporting -- not evidence about the treatment itself. See "Bundle
verification" below for the checkpoint after this one.

### Four-task paid qualification -- $11.52 ceiling

Same sequence and checkpoints, against `prepare_pier_qualification`/
`run_pier_qualification`: 16 cells across the four `REALISTIC_PILOT_FIXTURES`
tasks (`assert prepared.cells == 16 and prepared.evaluations == 32`),
$5.76 per arm. Validates repository navigation and sandboxed package
execution across a larger, more realistic grid before committing to the
full study. `ASSAY_ALLOW_PAID_PIER=1` and `OPENROUTER_API_KEY` are the same
two environment variables from the smoke run above -- approving smoke does
not carry over; this is its own independent operator decision at the moment
`run_pier_qualification` is actually called.

### Full paid study execution -- $34.56 ceiling

Same sequence and checkpoints, against `prepare_pier_full`/`run_pier_full`:
48 cells across all twelve `EXPERIMENT_TASKS`
(`assert prepared.cells == 48 and prepared.evaluations == 96`), $17.28 per
arm. Requires its own independent plan inspection and `allow_paid=True`
decision -- passing smoke or qualification is not a substitute, and
`_revalidate_before_dispatch` re-checks the plan's own runtime configuration
and cost ceilings against the live binding immediately before dispatch, not
merely once at preparation time.

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
partial artifacts existed. Find it with the exact scan
`qualify_local.py`'s own cancellation probe uses:

```python
import json

from assay.store import ObjectStore

store = ObjectStore(".assay/pier-smoke-v1")
traces = [
    json.loads(path.read_bytes())
    for path in sorted(store.objects.iterdir())
    if path.is_file()
]
cancellation_traces = [
    trace for trace in traces
    if isinstance(trace, dict) and trace.get("schema_version") == "assay-pier-cancellation-trace/0.1.0"
]
for trace in cancellation_traces:
    print(trace["coordinate"], "cleanup_incomplete:", trace["cleanup_incomplete"])
```

`cleanup_incomplete: true` means teardown was never confirmed complete --
treat any resources it might have left as possibly still live, not as
safely gone; combine this with the orphan check below before concluding a
cancelled run left nothing running.

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
  and `verify_artifact_bytes` gate every success on all four required kinds
  (`raw_trajectory`, `candidate`, `result`, `configuration`) being present,
  correctly sized, checksum-matched, and (where declared) valid UTF-8/JSON --
  a plausible-looking manifest with one wrong byte is a `ManifestRejected`
  failure, not a warning. The manifest is what binds those kinds and is never
  one of them: an entry for `manifest.json` would have to declare the checksum
  of the bytes carrying that checksum, so `ArtifactEntry` reserves the path.
- **Declared evidence that was never published.** Verifying the manifest and
  publishing the bytes it declares are separate steps, and the artifact byte
  ceilings apply to the second. `_settle` fails the cell with
  `UnpublishedEvidence` if any required kind resolves to no ref, rather than
  emitting a `WorkerSuccess` whose `result_ref`/`candidate_ref` are null --
  which downstream cannot distinguish from a trial that produced nothing.
  `manifest.json` is bounded by the per-artifact ceiling but is not charged to
  the aggregate one, on either side of the boundary: the aggregate bounds what
  a manifest may *declare*, so charging the binding document to it would make
  a manifest at the ceiling impossible to return or to publish in full. Both
  projects enforce that rule separately and both assert it against
  `tests/fixtures/pier_wire_contract.json`, since there is no import edge to
  keep the two copies aligned.
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
end -- automated and re-run on every pull request by
`pier_qualification/tests/test_pier_final_rehearsal.py::test_final_rehearsal_verifies_the_legacy_bundle_and_a_fresh_pier_bundle`:

```sh
cd experiments && uv run --locked pytest -q pier_qualification/tests/test_pier_final_rehearsal.py
```

It verifies the fixed legacy bundle recorded in this checkout (the same
fixture `tests/test_optional_jig.py` proves verifies in a wheel install with
no Jig at all), then generates and verifies a fresh Pier bundle from a real,
recorded qualification and a `smoke` preparation -- run through the real
`prepare_pier_smoke`/`run_pier_smoke` path against a fake bridge (never a
real credential; see the file's own docstring for exactly what "no Jig"
means for Pier specifically, since Pier's own adapter never imports Jig at
all). It then scans every byte of both exported report bundles for a
sentinel published to the store but never referenced by any artifact,
manifest, or report, confirming the export closure cannot reach it -- the
same "hidden/reference/other-arm byte never reaches..." property
`tests/test_pier_secrecy.py` proves at the packaging layer, checked again
here at the export/report boundary.

`pier_qualification.pier_experiment` requires `paa-contracts`, which is
declared only as a development dependency, not a wheel runtime dependency
(`pyproject.toml`'s `[dependency-groups]`, not `[project.optional-dependencies]`)
-- a real installed-wheel rehearsal of the Pier path, of the kind
`tests/test_optional_jig.py` runs for the legacy bundle, is not possible
until that gap is closed; recorded as a known limitation of this rehearsal,
not a claim it already covers.
