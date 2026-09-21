# Assay experiments

This standalone uv project contains experiment runners and qualification suites
that are intentionally excluded from the Assay wheel. It depends on the parent
checkout as an editable `assay[review]` dependency.

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

CI runs these commands without paid-service credentials. Receipt-backed tests
remain gated and require an explicit `ASSAY_RUN_RECEIPTS` checkout. Pruning the
root `legacy` and `typesafe` extras and their development dependencies is a
separate follow-up.
