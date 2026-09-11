# assay

Reproducible, paired experiments for agent systems. Assay materializes a study,
compiles an immutable content-addressed plan, executes the authorized grid via
narrow worker/evaluator adapters, and emits auditable PAA evidence.

The library API is authoritative. See the
[review remediation plan](docs/remediation-plan.md). Local design notes remain
in the intentionally untracked `comms/` directory.

## Install and check

Python 3.12+ and Git are required. Jig and the development PAA schema corpus are
pinned to immutable upstream commits over public HTTPS; sibling checkouts and
provider credentials are not required.

```sh
uv sync --locked
uv run ruff check src tests
uv run mypy src
uv run pytest -q
uv build
```

## Library workflow

1. Publish inputs and schemas into `assay.store.ObjectStore`. Materialize a
   `StudySnapshot` binding subject digests, arm configurations, evaluator
   identities, all realizations, and pinned PAA schemas.
2. Call `assay.planning.compile_plan` with the published snapshot reference,
   worker repeats, Jig revision, concurrency, exclusions, and optional per-arm
   cost estimates. Unpriced arms are explicitly unavailable. When supplying
   estimates, include every arm; the total is derived, not independently set.
3. Inspect the plan, serialize with `canonical_json`, and authorize those exact
   bytes by their `digest_bytes` hash. Pass both to `execute_plan`, alongside
   adapters whose `configuration()` matches the declared live settings.
4. Inspect `RunSucceeded` or `RunFailed`. Adapter failures are typed results;
   failed workers produce explicit unavailable evaluations. Persistence failure
   stops new scheduling, settles active calls, and returns recoverable progress.
5. Build a `ReportConfig` containing exact manifest and evaluator-record refs,
   reference/candidate arms, both repeat aggregations, and a seeded `paired-v2`
   statistical profile. Numeric reports require an explicit `scalar_direction`
   (`higher_is_better` or `lower_is_better`). Call `persist_report` to publish
   the config, common-subject sets, and reproducible report.

Scalar reports aggregate evaluator repeats before worker repeats, then resample
paired subjects. Below 10 common subjects inference is descriptive-only (the
arithmetic helper itself has no reporting floor). Ordinal categories are ordered
low to high and use an exact paired sign test without a numeric mapping.
Classification reports include confusion matrices and an exact paired
correctness test. Holm correction covers the declared candidate family;
confidence intervals are explicitly unadjusted. Missingness and cost coverage
are reported separately from effects. Unknown cost is never measured zero.

Export one manifest or report and its complete immutable reference closure:

```sh
assay export STORE sha256:ROOT_DIGEST DESTINATION
assay verify DESTINATION sha256:ROOT_DIGEST
```

Replace `sha256:ROOT_DIGEST` with the actual published reference. The destination
must be empty. Verification needs no network or installed PAA package: it uses
pinned schemas in the bundle, validates record bindings, rejects inserted or
missing objects, and recomputes reports. It proves integrity relative to the
supplied plan, not producer identity or that omitted real-world attempts never
happened. A working store can hold multiple roots; export before strict bundle
verification.

## Reproducibility and schema maintenance

Bootstrap sampling and arithmetic follow the versioned
[paired-v2 contract](docs/statistical-profile.md), independent of NumPy. Legacy
`paired-v1` report configurations are rejected rather than silently recomputed
using a changed algorithm. Existing run evidence can support a newly configured
v2 report.

Publication uses `staging/` outside `objects/sha256/`; interrupted-publication
residue there is not a committed bundle object. Unexpected entries in the
committed namespace are still rejected. Verification/report/export operations
share a bounded 16 MiB verified-byte cache, discarded after the operation;
evicted bytes are hash-checked again when read. Reference metadata is retained
for the operation. Execution retains output references, not payloads, and each
evaluation decodes the hash-verified published output afresh.

Wire schemas have an explicit seven-file inventory. Regenerate with
`uv run python -m assay.schema_export`; CI enforces
`uv run python -m assay.schema_export --check`. Tests anchor schema paths to the
repository rather than the invoking working directory.

## Consistency investigation and boundaries

`assay.investigations.consistency.materialize_consistency` supplies local
cosmetic, architectural, and semantic coding tasks under clean/inconsistent
repository conditions. `StructuralEvaluator` measures syntactic abstraction
reuse, not functional correctness; ambiguous implementations require an
explicitly configured judge. The end-to-end example in
[test_consistency.py](tests/test_consistency.py) covers both repeat axes,
an exclusion, an injected failure, ordinal reporting, and offline export.
Its synthetic worker tests the machinery; its results are not experimental
evidence about a real coding agent.

Production workers and ambiguity judges are caller-supplied adapters. The
included `JigWorker` accepts already-materialized prompt strings; it does not
silently stringify repository JSON. A coding-agent worker for the consistency
investigation must explicitly bind its repository/task input rendering and
output-source extraction in its configuration. Jig resources must expose stable
configuration, and system prompts must be static before authorization. Jig's
unqualified default cost totals are retained in traces but marked unavailable
for spend reporting. Authorized preparation stages and component-level PAA cost
aggregation are not supported; they are rejected explicitly. No paid or
production-agent experiment is included in acceptance testing.
