# Workflow edit experiment

This package belongs to the `experiments` uv project. `arms.py` defines the
four fixed arm identifiers, and `shape.py` validates the worker cell grid before
dispatch. The caller supplies the subject population and worker repeat count;
those study choices are not fixed by this scaffold.

Record implementation decisions in [DECISIONS.md](DECISIONS.md) before later
cohorts depend on them.
