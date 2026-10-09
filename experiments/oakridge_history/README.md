# Oakridge history study: versioned design record

This package fixes the inputs for a six-snapshot comparison of Oakridge's
workflow implementations. `run.py` resolves and archives pinned commits
without changing the Oakridge checkout, then calls the Assay Python API for
analysis and adjacent comparisons. Results are written under
`experiments/oakridge_history/results/`; keep real Oakridge results out of Git.

Run from `experiments/` with
`uv run python oakridge_history/run.py --oakridge PATH`. Add `--snapshot ID`
one or more times to regenerate selected snapshots
and available adjacent comparisons. After all six snapshots and five comparisons
exist, run `uv run python oakridge_history/run.py --summarize`. Summarization
reads only those stored JSON files and writes `summary/system.csv`,
`summary/components.csv`, `summary/coverage.csv`, and `summary.md`. A failed
containment guard stops a snapshot; a failed union-coverage guard stops the
summary.

Warm the npx cache before a measurement on a machine with network access:

```sh
npx --yes jscpd@5.4.0 --version
npx --yes dependency-cruiser@18.4.0 --version
```

Use Node v22.21.1 and npx 10.9.4. `metadata.json` records both versions and
dependency-cruiser 18.4.0, plus the Assay Git SHA and `uv.lock` digest. Assay's
`_preflight` requires `node` and `npx` on PATH for every run, even when jscpd
has no Python sources to analyze.

## Snapshot selection

Dates are UTC commit dates. The order in `snapshots.yaml` is the analysis order.

| ID | Date | PR | Event | Selection reason |
| --- | --- | --- | --- | --- |
| `s1-v2-introduced` | 2026-05-31 | #207 | v2 introduced | First committed v2 implementation. |
| `s2-pre-dbos` | 2026-08-14 | #415 | before DBOS | Baseline immediately before the DBOS implementation. |
| `s3-dbos-repaired` | 2026-08-17 | #434 | DBOS repaired | Captures the repaired DBOS implementation. |
| `s4-decision-rewrite` | 2026-08-30 | #469 | decision rewrite | Captures the decision rewrite boundary. |
| `s5-single-engine` | 2026-09-14 | #485 | single engine | Captures the single-engine implementation. |
| `pre-rewrite` | 2026-10-07 | #571 | pre-rewrite branch tip | Provisional comparison point before the rewrite. |

Assay numbers for three trees were seen during extractor validation. None
were used to choose these snapshots. The selections are historical events and
their pinned commits, rather than metric extrema.

`pre-rewrite` is provisional. Its manifest SHA is the observed `origin/main`
tip at #571; `final_sha: null` deliberately records that the final pin has not
been made. Before a final run, resolve the intended pre-rewrite boundary,
verify the candidate commit and date against its PR, put the immutable commit
in `final_sha`, update the manifest date and PR if necessary, rerun all six
snapshots and the guards, and record the changed pin in review. Do not silently
use the then-current branch tip.

## Scope and assignment

Only tracked source files beneath the five `include_paths` in `scope.yaml`
are in scope. A directory absent at a commit contributes nothing. The exclude
globs remove tests and fixtures before metrics are calculated. In particular,
the Rust v2 engine under `oakridge-core` is in scope at `s3` and `s4` even
though it was no longer operated: its code remained available for an agent to
couple to. The scope is about present code, not which engine was live.

Components are roles, not implementations. The same role can claim paths from
KBbL, Rust v2, and DBOS. Unclaimed modules remain `unassigned`; component
patterns intentionally cover the role-bearing subsets of the scoped trees.
Each mapping below was checked against the named snapshot's Git tree and a
representative source file at that commit. The role labels describe the code's
purpose and should be reviewed with the source when changed.

| Component | Source read at snapshot |
| --- | --- |
| orchestration | `s1-v2-introduced`: `kbbl/core/orchestrator/backends/dispatcher.ts`, `oakridge-core/src/executor/mod.rs`; `s3-dbos-repaired`: `oakridge-dbos/src/runtime/artifact-notifications.ts` |
| decision | `s4-decision-rewrite`: `oakridge-dbos/src/decision/commands.ts`, `oakridge-dbos/src/compiler/compile-workflow.ts` |
| review | `s1-v2-introduced`: `kbbl/core/review/atoms.ts` |
| collaboration | `s2-pre-dbos`: `oakridge-core/src/collab/mod.rs`; `s3-dbos-repaired`: `oakridge-dbos/src/domain/collaboration.ts` |
| adapters | `s1-v2-introduced`: `kbbl/adapters/claude-code/event-classifier.ts`; `s3-dbos-repaired`: `oakridge-dbos/src/adapters/kbbl.ts` |
| acp | `s5-single-engine`: `kbbl/core/acp/controller.ts` |
| skills | `s2-pre-dbos`: `kbbl/core/skills/registry.ts` |
| worktree | `s5-single-engine`: `kbbl/core/worktree/service.ts` |
| shared | `s1-v2-introduced`: `oakridge-core/src/types.rs`; `s2-pre-dbos`: `kbbl/core/shared/cohort-merge-contract.ts` |
| stream | `s1-v2-introduced`: `kbbl/core/stream/artifact-event-bus.ts` |

All `workflow-core/crates/` patterns are explicitly `post_rewrite_only`.
They are expected to match no module at these six snapshots.

Assay uses `fnmatchcase` for component assignment. Its `*` can cross `/` and
is not path-aware. For example, `kbbl/core/runtime*.ts` would also match a
future path beneath a `kbbl/core/runtime/` directory. A module claimed by two
components makes Assay fail with `AmbiguousComponentConfig`. The static
pattern-pair guard checks cross-component overlap without sampling modules.
It exactly handles literals and stars, including `**`; other fnmatch
operators fail closed until explicitly supported.

## Pattern guard

The original proposal equated each snapshot's unmatched patterns with absent
implementations. That equality is false: subpaths appear and disappear while
their implementation root remains present. At `s1`, several KBbL role paths
and Rust `collab` are unmatched despite both roots being populated; at `s3`,
DBOS `decision` is unmatched despite DBOS being present; at `s5`, old KBbL
orchestration and review paths are unmatched while `kbbl/core` persists.

The replacement has three checks: every pattern starts with a declared root
prefix; every ordinary pattern matches a module in at least one of the six
reports (the `post_rewrite_only` root is exempt); and each pattern beneath a
root whose include path resolved away at a snapshot appears in that snapshot's
unmatched set. Rooting and containment can run per snapshot. Union coverage
runs after all six reports exist. This preserves the useful absent-root
assertion without rejecting valid patterns for role subpaths that had not yet
appeared or had already retired.

## Summary columns

The snapshot system and component summary columns together are `snapshot_id`, `commit_sha`, `date`,
`pr_number`, `resolved_include_paths`, `files_seen`, `files_analyzed`,
`modules_discovered`, `files_without_module`, `module_count`, `edge_count`,
`component`, `component_module_count`, `unmatched_patterns`, `cycle_count`,
`modules_in_cycles`, `radon_sloc`, `radon_lloc`, `radon_cc`,
`radon_halstead_volume`, `complexipy_cognitive`, `grimp_imports`,
`ruff_violations`, `ruff_magic_values`, `mypy_errors`, `jscpd_clones`,
`jscpd_duplicated_lines`, and `maintainability_index_mean`.

The adjacent-pair summary columns are `before_snapshot_id`,
`after_snapshot_id`, `modules_added`, `modules_removed`, `edges_added`,
`edges_removed`, `components_added`, `components_removed`, `cycles_created`,
`cycles_resolved`, `cross_component_edges_added`,
`cross_component_edges_removed`, `new_lines`, `new_duplicated_lines`,
`new_max_nesting_depth`, and each metric's `before`, `after`, `delta`,
`provenance`, and `shared_file_count`. The runner should take values from
Assay's report and comparison fields, preserving nulls.

## Interpretation limits

The snapshots are selected events, not a continuous time series. Code
presence does not establish runtime use or causality. The role patterns leave
some modules unassigned; the reported unmatched set is evidence about module
paths, not just implementation presence. Python-only analyzers yield null
where a snapshot has no Python sources. Test files are excluded from metrics,
while production code may still contain imports or references to test
support; this test-exclusion asymmetry should be considered when interpreting
graph and coupling counts. Source movement, parser coverage, and changes to
third-party tool versions can alter results independently of code quality.
