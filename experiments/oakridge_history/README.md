# Oakridge history study: versioned design record

This package fixes the inputs for a six-snapshot comparison of Oakridge's
workflow implementations. It contains configuration, typed loaders, and pure
pattern guards only. A later runner produces reports outside this package.

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
Each mapping below was checked against source paths in the named snapshot's
Git tree; the role labels describe the code's purpose and should be reviewed
with the source when changed.

| Component | Source-path check snapshot |
| --- | --- |
| orchestration | `s1-v2-introduced` (`kbbl/core/orchestrator`, Rust executor/registry); `s3-dbos-repaired` (DBOS runtime/workflows) |
| decision | `s4-decision-rewrite` (DBOS decision/compiler) |
| review | `s1-v2-introduced` (`kbbl/core/review`) |
| collaboration | `s2-pre-dbos` (Rust `collab`); `s5-single-engine` (DBOS collaboration domain) |
| adapters | `s1-v2-introduced` (KBbL adapters); `s3-dbos-repaired` (DBOS adapters) |
| acp | `s5-single-engine` |
| skills | `s2-pre-dbos` and `s5-single-engine` |
| worktree | `s5-single-engine` |
| shared | `s1-v2-introduced` (KBbL types, Rust types); `s2-pre-dbos` (KBbL shared) |
| stream | `s1-v2-introduced` |

All `workflow-core/crates/` patterns are explicitly `post_rewrite_only`.
They are expected to match no module at these six snapshots.

Assay uses `fnmatchcase` for component assignment. Its `*` can cross `/` and
is not path-aware. For example, `kbbl/core/runtime*.ts` would also match a
future path beneath a `kbbl/core/runtime/` directory. A module claimed by two
components makes Assay fail with `AmbiguousComponentConfig`; pattern changes
must rerun the overlap test against real module paths.

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

The snapshot summary columns are `snapshot_id`, `commit_sha`, `date`,
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
