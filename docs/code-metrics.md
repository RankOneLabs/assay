# Code metrics

Install the optional analyzers with `uv sync --locked --extra code-metrics` or
`pip install 'assay[code-metrics]'`. Snapshot and comparison commands print the
canonical JSON reports (the optional `--json` flag selects the same format):

```sh
assay code-metrics snapshot PATH [--config FILE] [--exclude GLOB ...] [--json]
assay code-metrics compare BEFORE_PATH AFTER_PATH [--config FILE] [--exclude GLOB ...] [--json]
```

Each path is a directory. The CLI reads its Python files into a snapshot keyed
by relative path, decoding each as Python does (a coding declaration or BOM,
otherwise UTF-8). It skips symlinks and the `.git`, `.venv`, `venv`,
`node_modules`, `__pycache__`, `.assay`, `.claude`, `dist`, `build`,
`.mypy_cache`, `.pytest_cache`, and `.ruff_cache` directories. Each `--exclude`
adds a file or directory glob; the report's `configuration.excluded_directories` lists the
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

## Metric definitions

`analyze` returns an `assay-code-metrics-report/0.3.0` report and `compare`
an `assay-code-metrics-comparison/0.4.0` comparison. Earlier schema versions
stay in `schemas/`. Every graph count below is over first-party modules: the
modules of top-level packages in the snapshot. Imports of anything else are
listed in `graph.external_dependencies` and do not enter these counts.

### Coupling

- **fan-in** of module `m`: distinct first-party modules that directly import `m`.
- **fan-out** of module `m`: distinct first-party modules that `m` directly imports.
- **Ca** (`afferent`) of component `C`: distinct modules outside `C` that
  directly import a module inside `C`.
- **Ce** (`efferent`) of component `C`: distinct modules outside `C` that a
  module inside `C` directly imports. Ce counts the imported outside modules,
  not the members of `C` that have an outside dependency.
- **instability**: `Ce / (Ca + Ce)`, or `null` when `Ca + Ce` is 0. An isolated
  component has no instability, not an instability of 0.

`incoming_edges` and `outgoing_edges` count raw edges across the component's
boundary, so two members importing the same outside module add one to Ce and
two to `outgoing_edges`. Modules no configured pattern claims belong to the
`unassigned` component, which is reported like any other.

### Cohesion

For a component of `N` modules with `R` internal edges:

- **relational cohesion**: `(R + 1) / N`.
- **internal dependency density**: `R / (N * (N - 1))`, or `null` when `N` is 1.
- **internal edge share**: `R` over all edges touching the component (internal,
  incoming, and outgoing), or `null` when there are none. This is a supporting
  graph statistic, not a standard cohesion metric.

### Graph counts and cycles

- `module_count`: first-party modules.
- `first_party_edge_count`: first-party module-to-module edges.
- `cross_component_edge_count`: first-party edges whose two ends belong to
  different components. Without a component configuration every module is
  `unassigned`, so the count is 0.
- `cycles.components` lists every strongly connected component (SCC) with its
  members. `scc_count` counts them, `cyclic_scc_count` counts those that form
  a cycle (more than one module, or a module importing itself),
  `cyclic_module_count` counts the modules in them, and
  `largest_cyclic_scc_size` is the module count of the largest one (0 without
  a cycle).

### Propagation

- `reaches`: modules a module reaches directly or transitively, itself included.
- `reached_by`: modules that reach it, itself included.
- **fan-out visibility**: `reaches / N` for `N` modules.
- **fan-in visibility**: `reached_by / N`.
- **propagation cost**: the sum of `reaches` over `N * N`, which is the mean
  fan-out visibility. `null` for a snapshot with no modules.

Self-visibility is included throughout, so a graph with no edges has a
propagation cost of `1 / N`.

### Comparison

A comparison carries both absolute reports, the legacy metric `deltas`, and
`architecture_deltas`, each entry a `before`, `after`, and `delta`:

- `system`: propagation cost, first-party and cross-component edge counts, and
  the cyclic SCC, cyclic module, and largest cyclic SCC counts.
- `components`: Ca, Ce, instability, edge counts, and the three cohesion
  values for each component present on both sides.
- `modules`: fan-in and fan-out for each module present on both sides.
- `boundaries`: the edge count of each importer/imported component pair present
  on either side, with a missing side counted as 0.

A component or module present on one side only appears in
`structural_changes` (`components_added`, `modules_removed`, and so on) and has
no metric delta. A ratio's `delta` is `null` when either side is `null`.
`structural_changes.cross_component_edges_added` and
`cross_component_edges_removed` list each edge with both owning components. An
edge whose ends change owner between the sides is removed with its old owners
and added with its new ones.

Assay reports these measurements and differences without judging them: no
increase or decrease is marked better or worse.
