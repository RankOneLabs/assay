# Pier integration and qualification

Pier is the third-party (`datacurve-pier`) agent-execution provider Assay drives
through the isolated [`integrations/pier`](../integrations/pier/README.md)
bridge project. The bridge has its own lock and qualification script:

```sh
uv sync --locked --extra review --extra legacy
uv run ruff check integrations/pier
MYPYPATH=integrations/pier/src:experiments uv run mypy integrations/pier/scripts/qualify_local.py

cd integrations/pier
uv sync --locked --group dev
uv run mypy src
uv run pytest -q
```

`integrations/pier/scripts/qualify_local.py` validates the pinned bridge
identity, local container controls, guarded routing, artifact round trips,
accounting, and cancellation cleanup without a credential or network call.
It writes a `QualificationInventory` only after every probe passes.

The experiment runner, profiles, paid gates, bundle verification, recovery,
and rehearsal instructions now live in the
[`pier_qualification` README](../experiments/pier_qualification/README.md).
