# Code metrics

Install the optional analyzers with `uv sync --locked --extra code-metrics` or
`pip install 'assay[code-metrics]'`. Snapshot and comparison commands print the
canonical JSON reports (the optional `--json` flag selects the same format):

```sh
assay code-metrics snapshot PATH [--config FILE] [--exclude GLOB ...] [--json]
assay code-metrics compare BEFORE_PATH AFTER_PATH [--config FILE] [--exclude GLOB ...] [--json]
```

Each path is a directory. The CLI reads its Python files into a snapshot keyed
by relative path. It skips `.git`, `.venv`, `venv`, `node_modules`,
`__pycache__`, `.assay`, `.claude`, `dist`, `build`, `.mypy_cache`,
`.pytest_cache`, and `.ruff_cache` directories. Each `--exclude` adds a file or
directory glob; the report's `configuration.excluded_directories` lists the
resolved default names and supplied globs. The Python API accepts a snapshot
mapping directly and does not apply these exclusions.

`--config` accepts JSON or YAML with `clone_min_lines`, `clone_min_tokens`,
`ruff_ignore` (a list of rule names), and `components` (a list of objects with
`name` and `patterns`). For example:

```yaml
clone_min_lines: 5
clone_min_tokens: 50
ruff_ignore: []
components:
  - name: library
    patterns: ["src/assay/*.py"]
```

Clone detection uses pinned jscpd through `npx`. It needs Node.js, npm, and
network access for the first download.
