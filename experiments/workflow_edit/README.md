# Workflow edit experiment

This package belongs to the `experiments` uv project. `arms.py` defines the
four fixed arm identifiers, and `shape.py` validates the worker cell grid before
dispatch. The caller supplies the subject population and worker repeat count;
those study choices are not fixed by this scaffold.

Record implementation decisions in [DECISIONS.md](DECISIONS.md) before later
cohorts depend on them.

The study is now in Part 2a: a thin slice through one task, built against the
Part 2 spec, which lives outside this repository. Its operator decisions of
2026-10-15 are copied into DECISIONS.md. The wf-13 smoke below is Part 1's
qualification.

The fixture's dependency manifest and npm lockfile are committed under
[`integrations/pier/workflow_edit`](../../integrations/pier/workflow_edit/) so
the bridge image can install the locked tree at build time.

## Running a cell

`bridge.py` is the Assay side of the repository agent: `WorkflowEditBridgeClient`
is the `PierBridgeClient` that `PierAdapter` drives, and each agent turn is a
keyed Smithers job (`SmithersTurnCompletion`). `qualify.py` builds the
snapshot and an authorized `assay-execution-plan/0.3.0` plan with a capacity
ceiling and runs it through `execute_plan`; `evaluation.py` grades each
reconstructed patch against the fixture manifest's frozen test groups.

## wf-13 qualification smoke

The throwaway fixture is [`fixtures/smoke-edit`](fixtures/smoke-edit/README.md).
From `experiments/`, with mcbain reachable through Smithers:

```sh
docker build -t assay-pier-bridge:wf13 ../integrations/pier
IMAGE=$(docker image inspect --format '{{.Id}}' assay-pier-bridge:wf13)
uv run python -m workflow_edit.qualify smoke --image "$IMAGE"   # 20 live cells
uv run python -m workflow_edit.qualify probes --image "$IMAGE"  # typed rejections
uv run python -m workflow_edit.qualify diagnose                 # names failing tests
uv run python -m workflow_edit.qualify pricing                  # public catalogue only
uv run python -m workflow_edit.qualify wake                     # needs mcbain asleep
uv run python -m workflow_edit.publish                          # rewrites SMOKE.md
```

Each command writes a gzipped evidence file under `evidence/wf13/`, and
`publish` recomputes [SMOKE.md](SMOKE.md) from those files alone. The Assay
object store for a run defaults to `~/.assay-wf13/store`.
