# Workflow edit experiment

This package belongs to the `experiments` uv project. `arms.py` defines the
four fixed arm identifiers, and `shape.py` validates the worker cell grid before
dispatch. The caller supplies the subject population and worker repeat count;
those study choices are not fixed by this scaffold.

Record implementation decisions in [DECISIONS.md](DECISIONS.md) before later
cohorts depend on them.

The fixture's Node dependency manifest and npm lockfile are committed under
[`integrations/pier/workflow_edit`](../../integrations/pier/workflow_edit/) so
the bridge image can install the locked tree at build time.
