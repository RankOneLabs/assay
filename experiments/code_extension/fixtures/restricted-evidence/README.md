# Restricted evidence

Subject `oakridge-observation-restricted-evidence` gives the `restricted` field
sensitivity its own evidence kind, redaction reason and export allowance in oakridge's
observation app, at oakridge `1495ec34`. Its shape is the code's own: one list of evidence
kinds repeated across four layers (grading, producer classification, HTTP intake, export),
plus a policy flag and a credential gate. The precedent, `repository_content`, already
exists at every one of these points. Three of the edits are not pointed out by the type
checker:

- the runtime list of accepted kinds in `grading/evidence-packages/references.ts`;
- the zod enum on grade-context intake in `http/evaluations.ts`;
- the raw-credential gate in `http/exports.ts`.

The classification that collapses `restricted` to `internal` is also an untyped choice: it
type-checks either way.

## Provenance

Cut by `uv run python -m code_extension.slice --scenario restricted-evidence --oakridge
<oakridge>` from oakridge commit `1495ec34`. The slice spec in
`code_extension/library/observation_export.py` lists every pinned file and every edit made
while moving it.

| Fixture path | Source at the pin | Why included |
| --- | --- | --- |
| `src/**` | `observation/src/**`, the import closure of `createApp` (`http/app.ts`), which reaches the export route, grade-context intake, redaction, the export store and producer classification | The code the feature passes through |
| `canonical-json/src/index.ts` | same path | The workspace package the source imports |
| `tests/visible/export-redaction.test.ts` | `observation/tests/` | Public checks |
| `package.json`, `package-lock.json` | `integrations/pier/scenario_library/` | The image's dependency lock, renamed; versions match oakridge's `bun.lock` |
| `tsconfig.json` | authored | The pinned compiler options, flattened |

The repository has 72 files and 401,368 bytes, under the 200-file and 1,000,000-byte limits.

## Edits made while moving files

- Source keeps its depth (`observation/src/` becomes `src/`), so its relative imports are
  unchanged.
- `canonical-json` is imported by relative path instead of as a workspace package.
- Tests move down one directory, so `../src/` becomes `../../src/`.
- In `producers/oakridge/evidence-packages.ts`, two key separators inside template
  literals are raw NUL bytes at the pin. They are written as the `\u0000` escape, which is
  the same string, because the bridge refuses a working copy that holds NUL bytes.

No production behavior is changed.

## Hidden groups

- **Regression:** `classification.test.ts`, the pinned classification tests. It moved out
  of the visible tests because it asserts that `brief.files_in_scope` evidence is
  `internal`, which points straight at the classification edit and is the expectation the
  task reverses. The two assertions that say so (one table row, and the second line of the
  last test) are removed from this copy, so the group passes both before and after the
  feature. Their reversed expectation is checked in the new-behavior group.
- **New behavior:** `restricted-evidence.test.ts`. Titles start with `reachability:` when
  the test fails unless restricted evidence is produced by classification or carried from
  grade-context intake to export, and `semantics:` otherwise. The credential check uses
  `createApp({ db: {} as Database, credentials })`; the 403 comes before any database
  access.

## Patches

| Patch | What it does | Should fail |
| --- | --- | --- |
| `reference.patch` | Adds the kind at every layer, the reason, the flag and the gate | nothing |
| `unreachable-classification.patch` | Everything except classification, which still maps restricted fields to `internal` | reachability |
| `ungated-allowance.patch` | Everything except the gate, so a read token can export restricted content | semantics only |
