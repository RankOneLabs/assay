# assay

Reproducible, paired experiments for agent systems. Assay materializes a study,
compiles an immutable content-addressed plan, executes the authorized grid via
narrow worker/evaluator adapters, and emits auditable PAA evidence.

## Install

Python 3.13+, Git, and uv 0.10.2 are required (`python -m pip install "uv==0.10.2"`).

```sh
uv sync --locked
```

Optional extras:

| extra | adds |
|---|---|
| `review` | the browser review UI (`assay review serve`) |
| `code-metrics` | repository snapshot and comparison metrics ([docs](docs/code-metrics.md)); also needs Node.js and npm with `npx` on PATH |

## How it works

1. **Study.** Publish inputs and schemas into `assay.store.ObjectStore`, then
   materialize a `StudySnapshot` binding subject digests, arm configurations,
   evaluator identities, realizations, and pinned PAA schemas.
2. **Plan.** `assay.planning.compile_plan` takes the snapshot reference, worker
   repeats, concurrency, exclusions, and optional per-arm cost estimates.
   Unpriced arms are explicitly unavailable; when supplying estimates, include
   every arm — the total is derived, not set.
3. **Authorize and execute.** Serialize the plan with `canonical_json`, authorize
   those exact bytes by their `digest_bytes` hash, and pass both to
   `execute_plan` along with adapters whose `configuration()` matches the
   declared settings.
4. **Inspect.** Execution returns `RunSucceeded` or `RunFailed`. Adapter failures
   are typed results, and failed workers produce explicit unavailable
   evaluations. A persistence failure stops new scheduling, settles in-flight
   calls, and returns recoverable progress.
5. **Report.** Build a `ReportConfig` with manifest and evaluator-record refs,
   reference/candidate arms, repeat aggregations, and a seeded `paired-v2`
   statistical profile, then call `persist_report`.

An incomplete run lists its missing coordinates, stays inspectable through
`RunFailed`, and cannot be exported or reported on as a complete run.

## Reports

- **Scalar** reports aggregate evaluator repeats, then worker repeats, then
  bootstrap over paired subjects. They require an explicit `scalar_direction`
  (`higher_is_better` or `lower_is_better`). Below 10 common subjects, inference
  is descriptive only.
- **Ordinal** reports use an exact paired sign test with no numeric mapping.
- **Classification** reports include confusion matrices and an exact paired
  correctness test.

Holm correction covers the declared candidate family; confidence intervals are
unadjusted. Missingness and cost coverage are reported separately from effects,
and unknown cost is never treated as zero. Bootstrap sampling follows the
versioned [paired-v2 contract](docs/statistical-profile.md), independent of
NumPy.

Reports can pool population shards only when task, scope, contracts, arm and
evaluator declarations, repeat counts, and pricing assumptions all match.

## Export and verify

Export a manifest or report together with its full immutable reference closure,
then verify the bundle offline:

```sh
assay export STORE sha256:ROOT_DIGEST DESTINATION
assay verify DESTINATION sha256:ROOT_DIGEST
```

The destination must be empty. Verification needs no network access or installed
PAA package: it uses the schemas pinned in the bundle, validates record
bindings, rejects inserted or missing objects, and recomputes reports. It proves
integrity relative to the supplied plan, not producer identity.

Closure follows the declared reference fields of each artifact, not strings that
happen to look like hashes. Extension JSON can declare extra dependencies with
a reserved `assay_object_refs` array; see
[object references](docs/object-references.md).

## Review UI

```sh
uv sync --locked --extra review
uv run assay review serve /path/to/store
```

Open <http://127.0.0.1:7557>. The store path is the directory containing
`objects/`.

## Integrations

- [Pier](docs/pier-integration.md) — runs studies on the third-party Pier
  execution provider.
- [Code metrics](docs/code-metrics.md) — `assay code-metrics snapshot` and
  `assay code-metrics compare` for measuring repository changes.

## Development

```sh
uv sync --locked --extra review --extra legacy --extra code-metrics
uv run ruff check src tests experiments
uv run mypy src
uv run pytest -q
uv build
```

Wire schemas are generated from the models; regenerate them with
`uv run python -m assay.schema_export` (`--check` verifies they are current).

The review UI's built assets are committed in `src/assay/review/static`. After
changing `web/src`, rebuild them with Bun 1.3.10:

```sh
cd web
bun install --frozen-lockfile
bun run typecheck
bun run build
```
