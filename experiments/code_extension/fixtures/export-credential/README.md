# Export credential

Subject `oakridge-observation-export-credential` gives export its own credential in
oakridge's observation app, at oakridge `1495ec34`. It is a control: the edits are local,
in two files of one directory. `http/ingest-auth.ts` parses the new variable and keeps
tokens unique across capabilities, and `http/exports.ts` gates the export route on the new
credential. The one easy miss, the token-uniqueness list, is in the same function as the
parsing.

## Provenance

Cut by `uv run python -m code_extension.slice --scenario export-credential --oakridge
<oakridge>` from oakridge commit `1495ec34`. The slice spec in
`code_extension/library/observation_export.py` lists every pinned file and every edit made
while moving it. The source is the same as the `restricted-evidence` scenario's.

| Fixture path | Source at the pin | Why included |
| --- | --- | --- |
| `src/**` | `observation/src/**`, the import closure of `createApp` (`http/app.ts`) and of the shipped tests | The code the feature passes through |
| `canonical-json/src/index.ts` | same path | The workspace package the source imports |
| `tests/visible/{ingest-auth,export-redaction}.test.ts` | `observation/tests/` | Public checks; the database part of `ingest-auth.test.ts` skips without `OAKRIDGE_TEST_DATABASE_URL` |
| `tests/visible/database-fixture.ts` | `observation/tests/` | Imported by `ingest-auth.test.ts`; it opens no database by itself |
| `package.json`, `package-lock.json` | `integrations/pier/scenario_library/` | The image's dependency lock, renamed; versions match oakridge's `bun.lock` |
| `tsconfig.json` | authored | The pinned compiler options, flattened |

The repository has 74 files and 405,911 bytes, under the 200-file and 1,000,000-byte limits.

## Edits made while moving files

- Source keeps its depth (`observation/src/` becomes `src/`), so its relative imports are
  unchanged.
- `canonical-json` is imported by relative path instead of as a workspace package, in
  source and in `ingest-auth.test.ts`.
- Tests move down one directory, so `../src/` becomes `../../src/`.
- In `producers/oakridge/evidence-packages.ts`, two key separators inside template
  literals are raw NUL bytes at the pin. They are written as the `\u0000` escape, which is
  the same string, because the bridge refuses a working copy that holds NUL bytes.

No production behavior is changed.

## Hidden groups

- **Regression:** `classification.test.ts`, the pinned classification tests, unchanged.
  No shipped test points at this task's edit, so nothing moved for that reason; the file
  is there so the group exists.
- **New behavior:** `export-credential.test.ts`. Titles start with `reachability:` when
  the test fails unless a token configured in `OBSERVATION_EXPORT_CREDENTIALS` reaches the
  export gate, and `semantics:` otherwise. The route checks use
  `createApp({ db: {} as Database, credentials })`; the 403 comes before any database
  access, and a request that passes the gate fails on the empty database with a 500.

## Patches

| Patch | What it does | Should fail |
| --- | --- | --- |
| `reference.patch` | Parses the variable, keeps tokens unique, gates export on it instead of read | nothing |
| `unreachable-env.patch` | The route takes export credentials and the variable is parsed and checked, but the parsed list is left out of the returned credentials | reachability (and the empty-list check) |
| `read-still-exports.patch` | Export credentials work, but read credentials still export | semantics only |
| `tokens-not-unique.patch` | Export credentials work, but their tokens skip the uniqueness check | semantics only |
