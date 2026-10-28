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
is empty, its tool and prefix additions are empty, and its prompt addition is
absent. `append_code_intel_tools` preserves every baseline tool definition and
its position, then appends additions. The same rule applies to the prefix.
The baseline therefore leaves the existing st-v2 prompt and per-turn tool
digests intact.

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
before a run. The self-trust archive scanner retains its 16 study terms and
archive traversal, calls `scan_text`, and writes its CSV to
`experiments/verification_pilot/raw/self_trust/ledger/leak-scan.csv`.

This phase defines no indexer or model call. Index mount and agent visibility
remain operator choices.
