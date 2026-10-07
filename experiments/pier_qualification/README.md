# Pier qualification runner

Qualifies a local Pier runtime, then prepares and runs studies through it.
Bridge and adapter setup is covered in
[`docs/pier-integration.md`](../../docs/pier-integration.md).

## Checks

The root project, this experiments project, and the `integrations/pier` bridge
each have their own lock and are checked independently:

```sh
uv sync --locked --extra review --extra legacy
uv run ruff check integrations/pier
MYPYPATH=integrations/pier/src:experiments uv run mypy integrations/pier/scripts/qualify_local.py
cd experiments
uv run --locked pytest -q pier_qualification/tests/test_pier_acceptance.py

cd ../integrations/pier
uv sync --locked --group dev
uv run mypy src
uv run pytest -q
```

None of these need credentials. Docker-dependent tests skip when no daemon is
reachable.

## Qualify the local runtime

Every paid profile requires a recorded `QualificationInventory`
(`assay.runtime_inventory`). Produce one with:

```sh
uv run --extra review --extra legacy python integrations/pier/scripts/qualify_local.py
```

The script checks, in order:

- the bridge's pinned revisions, lock digest, and local image digest;
- that a real container enforces the trial's CPU, memory, pid, and `/scratch`
  limits, tears down cleanly, and leaves no `assay-pier-` containers behind;
- that the storage cap fails a deliberate overflow write with ENOSPC;
- that the image starts with no network access;
- the guarded OpenRouter route's fail-closed behavior, against a fake HTTP
  transport;
- artifact round trips, accounting, and cancellation cleanup, against a fake
  bridge client.

The first failing probe exits nonzero and writes nothing. On success the
inventory is published to `--output-dir` (default `.assay-pier-qualification`)
and its ref is printed:

```
qualified: sha256:...
```

The script never reads `OPENROUTER_API_KEY` and makes no network calls.

The Docker server version and the local image digest depend on the host, so
qualification can fail on a correctly configured machine whose values differ
from the pinned `EXPECTED_DOCKER_VERSION`/`PIER_BRIDGE_IMAGE_DIGEST`.

## Prepare a plan

Preparation compiles and publishes a plan without touching Docker, the network,
or money. Without an `inventory_ref`, it uses a synthetic default:

```python
from assay.investigations.correctness import DockerPythonRunner
from assay.store import ObjectStore
from pier_qualification.pier_experiment import prepare_pier_smoke

store = ObjectStore(".assay/pier-smoke-v1")
prepared = prepare_pier_smoke(store, runner=DockerPythonRunner())
```

| profile | prepare / run | cells | cost ceiling |
|---|---|---:|---:|
| smoke | `prepare_pier_smoke` / `run_pier_smoke` | 4 | $2.88 |
| qualification | `prepare_pier_qualification` / `run_pier_qualification` | 16 | $11.52 |
| full | `prepare_pier_full` / `run_pier_full` | 48 | $34.56 |

Inspect the plan and its reference closure before running it.

## Run a plan

A paid run requires all four of these; a missing one is rejected before
anything is dispatched:

1. `allow_paid=True` on the `run_pier_*` call for that profile;
2. `ASSAY_ALLOW_PAID_PIER=1` in the environment;
3. a real `OPENROUTER_API_KEY` in the environment;
4. an `inventory_ref` from a real `qualify_local.py` run on this machine.

Each profile is authorized on its own: approving smoke does not authorize
qualification or full.

```python
from pathlib import Path

from assay.canonical import digest_bytes
from pier_qualification.pier_experiment import prepare_pier_smoke, run_pier_smoke

prepared = prepare_pier_smoke(store, inventory_ref=inventory_ref, runner=DockerPythonRunner())
authorization = digest_bytes(store.read_bytes(prepared.plan_ref))

result = await run_pier_smoke(
    store,
    plan_ref=prepared.plan_ref,
    authorization=authorization,
    bridge=bridge_client,
    allow_paid=True,
    inventory_ref=inventory_ref,
    export_destination=Path(".assay/pier-smoke-v1-bundles"),
)
```

The plan's runtime configuration and cost ceilings are re-checked against the
live binding immediately before dispatch.

## Verify bundles

With an `export_destination`, a run writes `abstraction/` and `correctness/`
report bundles and verifies both before returning. Re-verify offline at any
time:

```sh
assay verify .assay/pier-smoke-v1-bundles/abstraction sha256:ABSTRACTION_REPORT_REF
assay verify .assay/pier-smoke-v1-bundles/correctness sha256:CORRECTNESS_REPORT_REF
```

## Cancellation and cleanup

A cancelled trial still publishes an `assay-pier-cancellation-trace/0.1.0`
object recording the coordinate, any partial artifacts, and
`cleanup_incomplete`. When `cleanup_incomplete` is true, treat the trial's
resources as possibly still live.

After any real trial, check for leftover containers:

```sh
docker ps -a --filter 'name=assay-pier-' --format '{{.Names}}'
```

Remove any you find with `docker rm -f <name>` and treat that trial's accounting
as `uncertain`.

## Failure outcomes

- **Worker exception.** Recorded as a `WorkerFailure` with
  `Accounting(coverage="uncertain")`: the trial was dispatched, so its cost is
  unknown, not zero.
- **Disagreeing exit status.** A trial succeeds only if both Pier's status and
  mini-swe-agent's embedded `exit_status` agree.
- **Bad artifact evidence.** All four required artifacts (`raw_trajectory`,
  `candidate`, `result`, `configuration`) must be present, correctly sized, and
  checksum-matched; otherwise the cell fails with `ManifestRejected`.
- **Unpublished evidence.** A verified manifest whose declared artifacts were not
  all published fails with `UnpublishedEvidence`.
- **Incomplete run.** A `RunManifest` with `status == "incomplete"` lists its
  `missing_coordinates` and is never treated as a complete run.
