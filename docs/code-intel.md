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

Delivery configuration requires an explicit absolute `index_mount` outside
`/workspace` and an explicit `index_agent_readable` flag. Neither has a default.
The operator supplies the mount for each provider comparison; a tool-delivered
index must be readable by the agent.

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
attempts and errors are counted per session in the ledger. The trajectory
carries host-recorded `code_intel_index: {"path": "...", "agent_readable": true}`
metadata. The delivery mount path is absolute and outside `/workspace`. The
shell inspection parser normalizes paths under the configured mount only for
this broad measure, so a successful read or grep of the index counts when the
trajectory says it is agent-readable. `codeintel_query` counts from its
structured result. The `index_agent_readable` flag declares the operator's
intended access policy; it is not an enforced access boundary for a preloaded
arm. In particular, an agent that owns an index file with mode `000` can
restore read permission with `chmod`. Interpret the measure using the declared
flag. Enforcing a boundary would require a separate root-owned, read-only mount
implementation.

## TypeScript symbols mode

`SymbolsMode` selects a host-side TypeScript and TSX indexer. The grammar is
`tree-sitter-typescript==0.23.2` in the `code-metrics` extra and in the asserted
pin table. `prepare()` indexes only delivered snapshot entries outside the
fixture-derived hidden-path set. It writes one JSON manifest under
`.assay/code-intel/indexes/`, keyed by the snapshot and image digests and an
indexer version containing the resolved grammar, `dependency-cruiser`, and
`typescript` versions. The manifest carries definitions, signatures,
references, AST structure, source provenance, and build time. A toolchain or
parser failure returns `codeintel_index_failure` before a query can run.

The `symbol` query returns definition spans and signature snippets with rank,
hash, token estimate, and query latency. `summarize()` lists files and their
first symbols in stable path order within its token budget. The capability
manifest advertises only `symbol` and notes dynamic `import()`, string-keyed
dispatch, and `any`-typed calls as cases static analysis cannot resolve. Call
edges and import graphs are reserved for the relationships phase.

## TypeScript relationships mode

`RelationshipsMode` adds three query kinds to the same host-side index:
`callers_and_callees`, `importers`, and `affected`. For calls, the query text
is `callers:<symbol>` or `callees:<symbol>`; a bare symbol returns both
directions. The importer and affected queries take a snapshot module path.
Each result is a context item with revision, source path, rank, content hash,
token estimate, retrieval method, and raw source reference. Call results
also carry the call's line range and a tagged `resolved` or `unresolved`
status. Import edges have no line range because the metrics graph does not
provide one.

The import graph comes directly from `code_metrics.typescript.extract_typescript_graph`.
The index stores its `ModuleGraphV2`, plus the `CycleReportV4` and
`PropagationReportV4` produced by `analyze_cycles` and `analyze_propagation`.
`importers` returns those graph edges without reconstructing imports. The
`affected` query follows those edges in reverse: a change to M affects M and
each module that transitively imports M. Its set size equals M's `reached_by`
count, which includes M itself. The propagation report retains counts rather
than member sets, so this reverse traversal is needed to list modules; the
query checks its result against the published `reached_by` count. Type-only
imports remain edges; unresolved and external imports remain external
dependencies in the metrics graph.

Call candidates come from the syntax tree already parsed for symbols. A
direct identifier call resolves only when it has one matching local or
imported definition in the snapshot. Dynamic `import()`, string-keyed
dispatch, and calls through an `any`-typed value remain visible with an
unresolved reason. Unknown or ambiguous targets are unresolved too. A graph
edge is a static inference, not proof that the call executes at runtime.
This analysis does not perform TypeScript type checking or full lexical
binding, so callers should treat its resolved edges as candidates to inspect.

Run `uv run python -m verification_pilot.self_trust.codeintel_fixtures
--relationships` from `experiments/` for the model-free cross-file caller
demonstration. Its synthetic snapshot omits an access guard in
`src/access.ts`, while the effect appears in `src/report.ts`. The script
reads the caller span with the bridge's Docker `read_file` tool, records query
latency and supplied tokens, and writes the pre-run leak scan to
`experiments/verification_pilot/raw/self_trust/ledger/codeintel-relationships-leak-scan.json`.

`verification_pilot.self_trust.codeintel_fixtures` runs scripted queries over
the `resume146`, `forge-move`, and `forge-rewrite` omission-owner trees with no
model call. It runs the contract's omission-coverage check and pre-run leak
scan, then writes the scan result to
`experiments/verification_pilot/raw/self_trust/ledger/codeintel-leak-scan.json`.

## Self-trust delivery

`VerificationPilotSettings.code_intel_delivery` holds the validated delivery
configuration: `mode`, `delivery`, `repository_revision`,
`max_context_tokens`, `query_limit`, `provider_options`, `index_mount`, and
`index_agent_readable`. The revision is the digest of the generated subject
tree. Baseline mode leaves the pinned prompt, prefix, and tool lists alone.
`symbols` and `relationships` use the existing TypeScript index; the latter
exposes its recorded references without adding an indexer.

Preloaded delivery inserts the summary into the final user prefix message,
directly before T1 with one blank line. Tool delivery appends `codeintel_query`
after each baseline per-turn tool list. It runs a dependency-free `python -c`
script inside the same sandbox as `read_file` and `search_files`. Each query
counts toward the existing 100-per-turn and 300-per-cell call ceilings, and
the configured query limit applies inside those ceilings. The trajectory
records the caps and actual calls and tokens.

The index is mounted outside `/workspace`. Bind storage writes `index.json`
into the host directory mounted at the configured path; tmpfs storage streams
it through `docker exec -i ... tar -x -C <mount>`. A failed population stops
the cell with `codeintel_index_failure` before its first model request. The
captured tree remains the existing `/workspace` tar stream, so the index does
not enter the submission diff or change the image digest. No delivery test
makes a model call.
