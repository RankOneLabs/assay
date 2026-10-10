# Assay experiments

A standalone uv project for experiment runners and qualification suites. It is
excluded from the Assay wheel and depends on the parent checkout as an editable
`assay[review,legacy]` dependency.

```console
uv sync --locked --group dev
uv run mypy .
uv run pytest -q
```

Lint from the repository root so the root Ruff configuration applies:

```console
cd ..
uv run ruff check experiments
```

Tests that depend on externally published reproduction bundles skip unless
`ASSAY_RUN_RECEIPTS` points at a checkout containing them. No test needs a paid
service credential.

| directory | contents |
|---|---|
| [`consistency_pilot`](consistency_pilot) | code-consistency pilots and the DRY experiment |
| [`pier_qualification`](pier_qualification/README.md) | Pier runtime qualification and study runner |
| [`typesafe_relevance`](typesafe_relevance/README.md) | Typesafe relevance study |
| [`code_metrics`](code_metrics) | code-metrics experiment helpers |
| [`oakridge_history`](oakridge_history/README.md) | Oakridge history study inputs and pattern guards |
