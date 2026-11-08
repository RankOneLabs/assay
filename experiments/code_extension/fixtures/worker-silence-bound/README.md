# Worker silence bound

Subject `oakridge-dbos-worker-silence-bound` lets a run's launch configuration set one
agent worker's silence bound. It is the first scenario of the library at oakridge
`1495ec34`. Its shape is the code's own: a configuration value parsed in `domain/`,
carried on the effect instruction, and applied in `effects/`. Two steps are not pointed
out by the type checker. The launch parser rebuilds each worker's settings field by
field, so a new field that is not copied there is silently dropped. The provider fixes its
bound once, when it is created, and its silence check has no instruction in scope.

## Provenance

Cut by `uv run python -m code_extension.slice --scenario worker-silence-bound --oakridge
<oakridge>` from oakridge commit `1495ec34`. The slice spec in `code_extension/library/worker_silence_bound.py`
lists every pinned file and every edit made while moving it.

| Fixture path | Source at the pin | Why included |
| --- | --- | --- |
| `src/**` | `oakridge-dbos/src/**`, the import closure of the launch parser, instruction builder and agent provider | The code the feature passes through |
| `kbbl/core/acp/{types,resumable-wire}.ts`, `kbbl/core/pwa/oakridge/operator-contracts.ts` | same paths | Types the kbbl adapter and provider import |
| `kbbl/core/server/handlers/{sessions,acp-per-sid}.ts` | same paths | Read as text by the hidden route-coverage test; not type-checked |
| `canonical-json/src/index.ts` | same path | The workspace package the definition store imports |
| `workflow-core/fixtures/bundles/{review-loop,fan-out,development}.json` | same paths | Sample workflows the tests read |
| `tests/visible/{run-config,effect-instruction}.test.ts` | `oakridge-dbos/tests/` | Public checks |
| `tests/visible/sample-workflow.ts` | authored | The one function these tests use from the pinned test fixture, which also opens Postgres and the Rust core |
| `package.json`, `package-lock.json` | `integrations/pier/scenario_library/` | The image's dependency lock, renamed; versions match oakridge's `bun.lock` |
| `tsconfig.json` | authored | The pinned compiler options, flattened |

The repository has 50 files and 479,788 bytes, under the 200-file and 1,000,000-byte limits.

## Edits made while moving files

- Source moves up one directory, so `../../../kbbl/...` imports become `../../kbbl/...`.
- `canonical-json` is imported by relative path instead of as a workspace package.
- Tests move down one directory, so `../src/` becomes `../../src/`.
- `effect-instruction.test.ts` imports `sample-workflow` instead of the pinned test fixture.

No production behavior is changed.

## Hidden groups

- **Regression:** `kbbl-adapter.test.ts`, the pinned provider and kbbl client tests. It
  moved out of the visible tests because it sets the provider's silence bound, which
  points at the edit the task should make the agent find.
- **New behavior:** `worker-silence-bound.test.ts`. Titles start with `reachability:` when
  the test fails unless the bound reaches the provider, and `semantics:` otherwise.

## Patches

| Patch | What it does | Should fail |
| --- | --- | --- |
| `reference.patch` | Parses, carries and applies the bound | nothing |
| `unreachable-provider.patch` | Parsed, typed and decoded, but the provider ignores it | reachability |
| `unreachable-parser.patch` | Provider applies it, but the parser drops it | reachability |
| `wrong-units.patch` | Reaches the provider but is read as seconds | semantics only |
