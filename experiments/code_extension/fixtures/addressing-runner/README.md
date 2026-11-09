# Addressing runner

Subject `oakridge-observation-addressing-runner` adds a code-graded question to oakridge's
observation app, at oakridge `1495ec34`: is this analysis finding addressed by at least one
proposed spec update? It is answered by a new `addressing` runner from a link view the
producer packages. Its shape is the code's own, the one `assessment.coverage` already has: a
runner registry, plus a producer/consumer contract carried in the evidence content. Two
steps are not pointed out by the type checker:

- The runner must be added to `runnerRegistry`. Nothing fails to compile without it, but no
  grading path can name the runner.
- The producer's assessment-window builder hard-codes the coverage link view. Packaging an
  addressing question through it fails ("subject must have a scoped brief criterion
  identity") until the builder makes the view the question needs.

This task shares its slice with `subject-only-build`; the start trees differ only in the
package name. It is the harder of the two.

## Provenance

Cut by `uv run python -m code_extension.slice --scenario addressing-runner --oakridge
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

The repository has 42 files and 152,875 bytes, under the 200-file and 1,000,000-byte limits.

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
  expectation, `{ definition_id: "definition-1", artifact_schema_version: "1" }`. Because it
  is built from `PILOT_QUESTION_IDS`, adding a question to the catalogue does not break the
  shipped tests' type check.

No production behavior is changed.

## Hidden groups

- **Regression:**
  - `recipe-dispatch.test.ts`, the pinned recipe dispatch tests. It moved out of the visible
    tests because it builds an assessment-window package through `runPackages`, which is the
    producer path the task should make the agent find.
  - `coverage-link-view.test.ts`, authored. It pins the coverage link view's content, its
    digest and the two evidence-set ids, all computed at the pin, and checks that the coverage
    runner still answers from the packaged view. Evidence-set digests depend on those bytes.
- **New behavior:** `addressing-runner.test.ts`. Titles start with `reachability:` when the
  test fails unless the runner is registered and the packaged view reaches it through
  `runPackages`, and `semantics:` otherwise. The tests build their own pinned expectations
  instead of importing the grading fixture, which needs `pg` and `kysely`.

## Patches

| Patch | What it does | Should fail |
| --- | --- | --- |
| `reference.patch` | Role, recipe and catalogue question, the runner and its registry entry, and the producer's addressing view | nothing |
| `unreachable-registry.patch` | Everything but the registry entry | reachability |
| `unreachable-producer.patch` | The runner is registered, but the producer still builds only the coverage view | reachability |
| `wrong-link-type.patch` | The runner counts a link of any type that names the finding | semantics only |
| `wrong-scope.patch` | The runner ignores the link's target scope | semantics only |

`unreachable-registry.patch` also fails the semantics tests that reach the runner through
`runnerEntry`, since an unregistered runner can't be reached any other way.
`unreachable-producer.patch` also fails the three semantics tests that read the packaged view.
