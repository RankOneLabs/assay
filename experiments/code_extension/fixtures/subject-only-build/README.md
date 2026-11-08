# Subject-only evidence build

Subject `oakridge-observation-subject-only-build` adds a `subject_only` evidence build to
oakridge's observation app, at oakridge `1495ec34`. It packages each supported subject item
on its own, from its subject slots alone. Its shape is the code's own: the build is a member of
a TypeScript union (`EvidenceBuild`) that has a runtime zod twin (`buildSchema`), and the
producer dispatches on it in another layer. The type checker forces the dispatch edit, because
the last branch narrows to `unscheduled_source`. It does not point at the zod twin. Without it,
`pinnedPilotRecipe` returns null for every `subject_only` pin, and `runPackages` refuses the
question as having no supported recipe.

This task shares its slice with `addressing-runner`; the start trees differ only in the
package name.

## Provenance

Cut by `uv run python -m code_extension.slice --scenario subject-only-build --oakridge
<oakridge>` from oakridge commit `1495ec34`. The slice spec in
`code_extension/library/observation_packages.py` lists every pinned file and every edit made
while moving it.

| Fixture path | Source at the pin | Why included |
| --- | --- | --- |
| `src/**` (29 files) | `observation/src/**`, the import closure of the evidence-package producer, the runner registry and the question catalogue | The code the feature passes through |
| `canonical-json/src/index.ts` | same path | The workspace package that digests evidence |
| `fixtures/oakridge/{analysis,plan,brief,assessment}-revision.json` | `observation/fixtures/oakridge/` | Sample revisions the extraction tests read |
| `tests/visible/{plan-traceability,classification,extraction-catalogue,extraction-issues}.test.ts` | `observation/tests/` | Public checks; none needs Postgres |
| `tests/visible/pilot-expectations.ts` | authored | The one value the tests read from the pinned grading fixture, which also opens Postgres |
| `package.json`, `package-lock.json` | `integrations/pier/scenario_library/` | The image's dependency lock, renamed; versions match oakridge's `bun.lock` |
| `tsconfig.json` | authored | The pinned compiler options, flattened |

The repository has 42 files and 152,878 bytes, under the 200-file and 1,000,000-byte limits.

## Edits made while moving files

- `canonical-json` is imported by relative path instead of as a workspace package (7 source
  files).
- Two template strings in `src/producers/oakridge/evidence-packages.ts` hold a literal NUL
  byte. They are written as the `\u0000` escape, the same runtime string, so a submission that
  edits the file is not refused as binary.
- Tests move down one directory, so `../src/` becomes `../../src/`, and
  `../fixtures/oakridge/` becomes `../../fixtures/oakridge/`.
- `plan-traceability.test.ts` imports `pilot-expectations` instead of the pinned grading
  fixture. The authored helper gives every catalogue question the pinned fixture's one
  expectation, `{ definition_id: "definition-1", artifact_schema_version: "1" }`.

No production behavior is changed.

## Hidden groups

- **Regression:** `recipe-dispatch.test.ts`, the pinned recipe dispatch tests. It moved out of
  the visible tests because it shows that a pin is read through a runtime schema and that a
  refused pin surfaces as "no supported captured evidence recipe", which points at the zod
  twin the task should make the agent find.
- **New behavior:** `subject-only-build.test.ts`. Titles start with `reachability:` when the
  test fails unless a `subject_only` pin is read and built on the normal `runPackages` path,
  and `semantics:` otherwise. The tests build their own pinned expectations instead of
  importing the grading fixture, which needs `pg` and `kysely`.

## Patches

| Patch | What it does | Should fail |
| --- | --- | --- |
| `reference.patch` | Union, runtime schema, a refusal of non-subject slots, a builder and the dispatch | nothing |
| `unreachable-schema.patch` | Builder and dispatch, but the runtime schema lacks the build | reachability |
| `wrong-all-revisions.patch` | Packages every revision of the subject kind, including unsupported provenance | semantics only |
| `wrong-accepts-linked-slots.patch` | Reads a `subject_only` pin that names a linked or unscheduled slot | semantics only |
