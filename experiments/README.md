# Assay experiments

This standalone uv project contains experiment runners and qualification suites
that are intentionally excluded from the Assay wheel. It depends on the parent
checkout as an editable `assay[review,legacy]` dependency so the pilots use the
same OpenAI major version as the qualified root legacy stack.

```console
uv sync --locked --group dev
uv run mypy .
uv run pytest -q
```

Lint remains rooted in the repository so the root Ruff configuration is the
single source of truth:

```console
cd ..
uv run ruff check experiments
```

CI lints this tree from the repository root, then syncs, type-checks, and tests
it from this directory against `experiments/uv.lock`. It never sets paid-service
credentials. Receipt-backed tests remain gated and require an explicit
`ASSAY_RUN_RECEIPTS` checkout. Pruning the root `legacy` and `typesafe` extras
and their development dependencies is a separate follow-up.
