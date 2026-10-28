# Code intelligence contract

`assay.code_intel` is a first-party package that studies can import without
importing the verification pilot. Its wire artifacts are the checked
`assay-codeintel-*` schemas in `schemas/`.

`CodeIntelSettings(mode=BaselineMode())` selects the baseline implementation
through `select_code_intel`. The contract has `prepare`, `capabilities`,
`query`, `summarize`, `tools`, `prompt_block`, `prefix_block`, and `close`.
Fallible calls return the package-local `Ok` or `Err` result. Errors carry an
operation, entity ID, detail, and `codeintel_` cause; this prefix does not
match the study's model-provider exclusion prefix.

The baseline declares no query kinds and no summary capability. Its summary
result is absent, its tool and prefix additions are empty, and its prompt addition is
absent. `append_code_intel_tools` preserves every baseline tool definition and
its position, then appends additions. The same rule applies to the prefix.
The baseline therefore leaves the existing st-v2 prompt and per-turn tool
digests intact.

`VerificationPilotSettings.code_intel` selects the mode for a study through
configuration. The pilot bridge applies that selection to its prompt, prefix,
and per-turn tool lists. Baseline adds no bytes to any arm. The self-trust
matched arms retain their separately pinned system framing, so cross-arm
prompt comparisons expect only the study's pre-existing framing differences;
the six prefix variants retain their declared placement and log order.

## Snapshot and index identity

The bridge delivers only entries whose package paths start with `workspace/`,
with that prefix stripped. `delivered_workspace` mirrors this rule.
`repo_revision` hashes the canonical JSON of the resulting `dict[str, str]`
subject tree. This is necessary because fixtures have no commit, and each
omission owner can produce a different tree. The index cache key hashes the
triple of snapshot digest, image digest, and indexer version. A manifest
records all three inputs and the key. `current_index` returns
`codeintel_stale_index` if its recorded snapshot digest disagrees with the
session tree.

`hidden_paths` derives exclusions from a fixture's `hidden_test` field;
`hidden_sources` pairs that path with its `hidden_tests` source text.
`make_index_manifest` keeps only indexed paths present in the snapshot and
outside that exclusion set. `check_omission_coverage` checks a hand-built
manifest against the fixture's `omission_paths` values before a study can
attribute an uncovered omission to an agent.

## Leak scan

`scan_text` takes term patterns and hidden paths, returns typed hits, and uses
the existing 80-character context on either side of a match. `scan_pre_run`
scans the serialized index manifest, preloaded summary, and query results
before a run. It can also match the fixture's declared hidden test source.
The self-trust archive scanner retains its 16 study terms and
archive traversal, calls `scan_text`, and writes its CSV to
`experiments/verification_pilot/raw/self_trust/ledger/leak-scan.csv`.

This phase defines no indexer or model call. Index mount and agent visibility
remain operator choices.

## Self-trust accounting

The study excludes `codeintel_index_failure` and `codeintel_stale_index` through
the same denominator rule as model-provider failures, while recording their
terminal status as `codeintel_failure`. The report lists each cause separately.
This does not change the strict `module_read` measure or the replacement rule.
The operator permits a `codeintel_`-excluded original session to use the one
visible replacement that `replacement_for` allows.

The broad `module_read_any` measure is published for T1, T2 and T3 beside
`module_read`. A successful `codeintel_query` counts only when its returned
`QueryResult` JSON has an item whose `file_path` is the omission module. Query
attempts and errors are counted per session in the ledger. For shell reads and
greps, or a direct `read_file` of an index, the trajectory must carry host-recorded
`code_intel_index: {"path": "...", "agent_readable": true}` metadata; the
path is relative to `/workspace`, and the route counts only when
`agent_readable` is true. The existing shell inspection parser supplies virtual
reads and searches for shell calls; direct `read_file` needs no expansion.
