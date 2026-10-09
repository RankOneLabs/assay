# Oakridge history study: versioned design record

This package fixes the inputs for a six-snapshot comparison of Oakridge's
workflow implementations. `run.py` resolves and archives pinned commits
without changing the Oakridge checkout, then calls the Assay Python API for
analysis and adjacent comparisons. Results are written under
`experiments/oakridge_history/results/`, which Git ignores.

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

Node v22.21.1 and npx 10.9.4 are the reference pins. `metadata.json` records
the actual and reference versions, dependency-cruiser 18.4.0, the Assay Git
SHA, and the `uv.lock` digest. `build_metadata(..., strict_runtime_pins=True)`
can enforce exact Node and npx pins for a controlled measurement. Assay's
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

`summary.md` displays each adjacent pair's structural counts, new-code
counts, and each metric's `before`, `after`, and `delta` values. The stored
comparison JSON also retains Assay's `provenance` and `shared_file_count`
fields, including nulls.

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

## Validation record (Sec 12, executed)

Environment captured before the first measurement: Node `v22.21.1`, npx `10.9.4`, dependency-cruiser `18.4.0`, TypeScript `6.0.3`, jscpd `5.4.0`; Assay Git SHA `1258981940c43f677b4ddf97eedf70892ac3cf08`; `experiments/uv.lock` SHA-256 `de693e3666469621870e6703e7d8777fbd7947a3e9cff3048cd51b104b6cbc28`. The installed Python dependencies passed Assay’s pinned-tool check. The registry was unavailable (`EAI_AGAIN`), so the already cached exact-version analyzer binaries were invoked via a temporary npx shim; the locked experiments virtual environment was used directly because `uv run --locked --offline` could not write to the sandboxed uv cache. Both runs used that same environment and shim.

The executed checks were: six pinned SHAs resolved and archived; all six metadata and reports and five adjacent comparisons completed; archive file-list SHA-256 digests and environment fields were present in each metadata file; report Assay version and committed component configuration were constant (language-conditional `versions.tools` entries vary with the language mix); the three-part pattern guard passed; each `module_components` assignment was checked against its snapshot Git tree directory listing and its unique configured role pattern; no `AmbiguousComponentConfig` occurred; coverage was reviewed for every language and pair; null existing and new-code fields were confirmed; the summary CSV and Markdown values were checked against the committed reports and comparisons; the second full run reproduced all eleven report/comparison files byte-for-byte.

The original Sec 12 unmatched-set equality was replaced because valid role subpaths can be absent while their implementation root exists. The passing three-part guard checks (1) every pattern is rooted under a declared implementation prefix, (2) every ordinary pattern matches a module in at least one snapshot, exempting `workflow-core` patterns marked `post_rewrite_only`, and (3) every pattern under an include path resolved away by the runner’s Git-tree resolution appears in that snapshot’s unmatched set. The expected-absent set came from each metadata file’s `resolved_away_include_paths`, which is produced by the runner’s `git ls-tree` resolution.

Unmatched patterns below are the complete report lists. “Root absent” means the runner resolved away that include path at this commit; “subpath absent” means the include path exists but that role path matches no module.

### s1-v2-introduced

Commit `d3c2ef813d03b3bfd8dba4a3eec60edcf748193f`; archive file-list SHA-256 `fa94278bb63caa5f7cef5d63607f3f9d68dbcede9d6754fdab82bf13584b0715`.

- `oakridge-dbos/src/runtime/**` — root absent.
- `oakridge-dbos/src/workflows/**` — root absent.
- `workflow-core/crates/orchestrator/**` — root absent.
- `oakridge-dbos/src/decision/**` — root absent.
- `oakridge-dbos/src/compiler/**` — root absent.
- `workflow-core/crates/decision/**` — root absent.
- `workflow-core/crates/review/**` — root absent.
- `oakridge-core/src/collab/**` — subpath absent.
- `oakridge-dbos/src/domain/collaboration.ts` — root absent.
- `workflow-core/crates/collab/**` — root absent.
- `oakridge-dbos/src/adapters/**` — root absent.
- `workflow-core/crates/adapters/**` — root absent.
- `kbbl/core/acp/**` — subpath absent.
- `workflow-core/crates/acp/**` — root absent.
- `kbbl/core/skills/**` — subpath absent.
- `workflow-core/crates/skills/**` — root absent.
- `kbbl/core/worktree/**` — subpath absent.
- `workflow-core/crates/worktree/**` — root absent.
- `kbbl/core/shared/**` — subpath absent.
- `workflow-core/crates/shared/**` — root absent.
- `workflow-core/crates/stream/**` — root absent.

### s2-pre-dbos

Commit `a74055c4228517794f93cca840dabe471ab4c99a`; archive file-list SHA-256 `80f6d6e3ba789f77e2cc43a8c651cc09e7391d1600e26a5b38eb81b451192342`.

- `oakridge-dbos/src/runtime/**` — root absent.
- `oakridge-dbos/src/workflows/**` — root absent.
- `workflow-core/crates/orchestrator/**` — root absent.
- `oakridge-dbos/src/decision/**` — root absent.
- `oakridge-dbos/src/compiler/**` — root absent.
- `workflow-core/crates/decision/**` — root absent.
- `workflow-core/crates/review/**` — root absent.
- `oakridge-dbos/src/domain/collaboration.ts` — root absent.
- `workflow-core/crates/collab/**` — root absent.
- `oakridge-dbos/src/adapters/**` — root absent.
- `workflow-core/crates/adapters/**` — root absent.
- `kbbl/core/acp/**` — subpath absent.
- `workflow-core/crates/acp/**` — root absent.
- `workflow-core/crates/skills/**` — root absent.
- `kbbl/core/worktree/**` — subpath absent.
- `workflow-core/crates/worktree/**` — root absent.
- `workflow-core/crates/shared/**` — root absent.
- `workflow-core/crates/stream/**` — root absent.

### s3-dbos-repaired

Commit `f101e6e36f1bd5d727aa8d1b744ffa88f0000096`; archive file-list SHA-256 `4ab65e4c0a552d0a84781a538c396978280e2439aeb91cde47f1a00afdb46fc1`.

- `workflow-core/crates/orchestrator/**` — root absent.
- `oakridge-dbos/src/decision/**` — subpath absent.
- `workflow-core/crates/decision/**` — root absent.
- `workflow-core/crates/review/**` — root absent.
- `workflow-core/crates/collab/**` — root absent.
- `workflow-core/crates/adapters/**` — root absent.
- `kbbl/core/acp/**` — subpath absent.
- `workflow-core/crates/acp/**` — root absent.
- `workflow-core/crates/skills/**` — root absent.
- `kbbl/core/worktree/**` — subpath absent.
- `workflow-core/crates/worktree/**` — root absent.
- `workflow-core/crates/shared/**` — root absent.
- `workflow-core/crates/stream/**` — root absent.

### s4-decision-rewrite

Commit `c060ba43252b88c70309344570c6688eb4d32fe6`; archive file-list SHA-256 `bb5866c626aeb93def9a8178c365bd2d7674b93705c38d453ea753f47eb7f0e5`.

- `workflow-core/crates/orchestrator/**` — root absent.
- `workflow-core/crates/decision/**` — root absent.
- `workflow-core/crates/review/**` — root absent.
- `workflow-core/crates/collab/**` — root absent.
- `workflow-core/crates/adapters/**` — root absent.
- `kbbl/core/acp/**` — subpath absent.
- `workflow-core/crates/acp/**` — root absent.
- `workflow-core/crates/skills/**` — root absent.
- `kbbl/core/worktree/**` — subpath absent.
- `workflow-core/crates/worktree/**` — root absent.
- `workflow-core/crates/shared/**` — root absent.
- `workflow-core/crates/stream/**` — root absent.

### s5-single-engine

Commit `4fdb4505d6ebe33282ff98b3c84cdbec94800b5b`; archive file-list SHA-256 `838d31a55ed80a189fc129d68ff71ad81c9da97bff8d74cbe2382f638568ec19`.

- `kbbl/core/orchestrator/**` — subpath absent.
- `oakridge-core/src/executor/**` — root absent.
- `oakridge-core/src/registry/**` — root absent.
- `oakridge-core/src/scheduler.rs` — root absent.
- `workflow-core/crates/orchestrator/**` — root absent.
- `workflow-core/crates/decision/**` — root absent.
- `kbbl/core/review/**` — subpath absent.
- `workflow-core/crates/review/**` — root absent.
- `oakridge-core/src/collab/**` — root absent.
- `workflow-core/crates/collab/**` — root absent.
- `kbbl/adapters/**` — root absent.
- `workflow-core/crates/adapters/**` — root absent.
- `workflow-core/crates/acp/**` — root absent.
- `workflow-core/crates/skills/**` — root absent.
- `workflow-core/crates/worktree/**` — root absent.
- `kbbl/core/shared/**` — subpath absent.
- `kbbl/core/types/**` — subpath absent.
- `oakridge-core/src/types.rs` — root absent.
- `workflow-core/crates/shared/**` — root absent.
- `kbbl/core/stream/**` — subpath absent.
- `workflow-core/crates/stream/**` — root absent.

### pre-rewrite

Commit `f3b3ffca43e43672ff2f58ab797d65c7532aaed8`; archive file-list SHA-256 `ebde6d9b3261b112ce28ba8e635f032977d397fb269b90a30d1b1fd3622b314b`.

- `kbbl/core/orchestrator/**` — subpath absent.
- `oakridge-core/src/executor/**` — root absent.
- `oakridge-core/src/registry/**` — root absent.
- `oakridge-core/src/scheduler.rs` — root absent.
- `workflow-core/crates/orchestrator/**` — root absent.
- `workflow-core/crates/decision/**` — root absent.
- `kbbl/core/review/**` — subpath absent.
- `workflow-core/crates/review/**` — root absent.
- `oakridge-core/src/collab/**` — root absent.
- `workflow-core/crates/collab/**` — root absent.
- `kbbl/adapters/**` — root absent.
- `workflow-core/crates/adapters/**` — root absent.
- `workflow-core/crates/acp/**` — root absent.
- `workflow-core/crates/skills/**` — root absent.
- `workflow-core/crates/worktree/**` — root absent.
- `kbbl/core/shared/**` — subpath absent.
- `kbbl/core/types/**` — subpath absent.
- `oakridge-core/src/types.rs` — root absent.
- `workflow-core/crates/shared/**` — root absent.
- `kbbl/core/stream/**` — subpath absent.
- `workflow-core/crates/stream/**` — root absent.

Coverage finding: `files_without_module` is zero in Python, Rust, and TypeScript at all six snapshots; there is no adjacent jump. Python has zero tracked in-scope files throughout, so every `existing_metrics` scalar and every comparison `new_code` value is null. Rust inline `#[cfg(test)]` modules stay in scope while TypeScript test files are excluded by glob. Removing the inline test modules from a temporary copy and rebuilding the Rust graph found files whose outgoing edges came only from those modules: s1 `0`, s2 `0`, s3 `0`, s4 `0` (s5 and pre-rewrite have no Rust files). This bounds one effect but does not make Rust and TypeScript component edge or cohesion counts directly comparable.

Reproducibility method: the second run used the same machine, Node, Python environment, exact cached analyzers, manifest, and Oakridge Git archive. SHA-256 digests of each `code-metrics.json` and comparison were compared with the first run; all eleven matched. This establishes same-machine determinism for these inputs, not cross-machine portability.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `snapshots/pre-rewrite/code-metrics.json` | 398359 | `33fb9457c7c884f25965fea06ac7d5db70bd599ad218d6f9e9de7e39773e53f8` |
| `snapshots/pre-rewrite/metadata.json` | 1669 | `306f9356a9bbdde11a81964bb28bfecf551c796915c4b3d1db1a07d4b40dd1c0` |
| `snapshots/s1-v2-introduced/code-metrics.json` | 206949 | `37c633e8ea8a659a0e7fc805aeffb713995f07b99a03dae678f203f3da6d7ec9` |
| `snapshots/s1-v2-introduced/metadata.json` | 1665 | `ee728a1ec5a646296968a71873af25687ca4f6b0390d511d7792f6d0cac676e4` |
| `snapshots/s2-pre-dbos/code-metrics.json` | 353103 | `250989af0ed15d1826b4cdd1ab2356ff5593040c89edbeda9f19af60ff581f26` |
| `snapshots/s2-pre-dbos/metadata.json` | 1666 | `63111764d08ac9deb7eeea054baeecda3255548dc74da12b1a9e2880f42eb601` |
| `snapshots/s3-dbos-repaired/code-metrics.json` | 453336 | `fc3deb1ed0869621543553f12ba6a41b1137556fc45fda150d18b76cfcdcba8d` |
| `snapshots/s3-dbos-repaired/metadata.json` | 1680 | `de3ff0c9ece9aee1343227c7287ffe1b107eb4a3a33e2e1d24dfa43fa14f6d36` |
| `snapshots/s4-decision-rewrite/code-metrics.json` | 469178 | `16f6e9696623860fb3ccd0c89e07ceeb1e777793df6c4513bc3ead0f86a86257` |
| `snapshots/s4-decision-rewrite/metadata.json` | 1747 | `72f75070c34ee5ff8d8b210af1a8fd59b3506779b8c87a9424ca345d22a86312` |
| `snapshots/s5-single-engine/code-metrics.json` | 310994 | `a4cb2766de2fd4cf5938e2d6e52076778f2f1f64cb6233f768fff8ad619f6d58` |
| `snapshots/s5-single-engine/metadata.json` | 1672 | `bcc1fa69c9cdedb13b944b08af5d3a5004a352c96e85885585c760f0ceca50df` |
| `comparisons/s1-v2-introduced__s2-pre-dbos.json` | 667108 | `6ad96890fcd788af0c45ba0056eb99ccc8fc2c28665cd24c9eccc1576b95ae3e` |
| `comparisons/s2-pre-dbos__s3-dbos-repaired.json` | 928030 | `5025a1b26e951e04832f4014fb3759015a638817d36e8798711115a8d957786f` |
| `comparisons/s3-dbos-repaired__s4-decision-rewrite.json` | 1073927 | `8b9c5ff33601470a5dab58e2a73203f1967745a82f251d7d93e8c7449c31bed6` |
| `comparisons/s4-decision-rewrite__s5-single-engine.json` | 941634 | `89f1aeb6e9f22affef817ceea25458872610b9d2ee509f1d78ccbaa2527970e8` |
| `comparisons/s5-single-engine__pre-rewrite.json` | 825550 | `e4665f45a34f417fc57f1f31ff89bc3f32305d05a4b483e4bcbb492f530f8927` |
| `summary/components.csv` | 1383 | `4de0614ab258ab6aa67e2e78a0e45be80a55d28f743a18360ea4e871fa50dd54` |
| `summary/coverage.csv` | 702 | `95d8c547f1fda038345a85a660de5d7f3b8d3be2211ed23d3896d0b0d27576db` |
| `summary/system.csv` | 4396 | `1d74cc97553b17e479aa43f89f527c84f49887419e4a79678100d5632cc053a1` |
| `summary.md` | 6547 | `9dafb85bc6681e7b36282c148fda1e33cc67949950d82bbbe7574c66a3e74184` |

The table lists every committed data artifact size and digest. The three CSVs contain only their declared summary columns; full reports remain in the JSON files.

`pre-rewrite` remains provisional at `f3b3ffca43e43672ff2f58ab797d65c7532aaed8` (`final_sha: null`). For a final boundary, verify the candidate commit and date against its PR, set `final_sha` in `snapshots.yaml` and update the manifest date/PR as needed, then regenerate the `pre-rewrite` report and its adjacent comparison from the archive and rerun the guards and summary. Record both the provisional and final SHAs; never patch the old JSON in place.

Validation gates: root Ruff, mypy, and schema-export checks passed; root pytest passed (`689 passed`); Oakridge-history pytest passed (`20 passed`). The virtual environments were reused with `--no-sync` and `PYTHONPATH` set to this worktree because a fresh `uv run` could not write the sandboxed uv cache.
