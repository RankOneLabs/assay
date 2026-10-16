# Verification pilot fixture decisions

## 7.1 selection, recorded before generator implementation

Read 7.1's “stay off every Part 2 anchor” at symbol level: no migration renames
readJsonPointer. This is the chosen reading of 7.1. The pinned slice has
`readJsonPointer` uses in fewer than six using files, so it cannot enter the
eligible population. The file-level reading would leave too few migrations.

The source is the committed 62-file `workflow_edit/fixtures/smoke-edit/repository`
tree, adapted from oakridge-dbos commit
`f3b3ffca43e43672ff2f58ab797d65c7532aaed8`. The source-tree commit in
this repository is `a20f94dd19c5b5d29939f4ed34a650a6d7368908`.
It contains 348,936 UTF-8 bytes and its `workflow_tree_digest` is
`sha256:a4039feafdf6061711fc040281108a65076fbbd1cfa8d3aacaac935374c6cfca`.
The pilot copies this tree without widening the wf-13 boundary.

I scanned `src/**/*.ts` for exported `const`, `function`, `type`, `interface`,
`class`, and `enum` declarations, then scanned all 62 fixture files for
identifier-boundary occurrences. The preliminary scan counted 14 eligible
exports; a broad token scan counts 16 because it includes generic names whose
occurrences are not all references to the declaration. Object keys were scanned
separately as property declarations and JSON keys. The following four have at
least six intended use occurrences in at least six distinct using files:

| old → new | kind and defining module | intended uses | using files | top-level directories |
| --- | --- | ---: | ---: | ---: |
| `JsonValue` → `PilotJsonValue` | type, `src/domain/primitives.ts` | 94 | 21 | 4 |
| `StageInstanceId` → `PilotStageInstanceId` | type, `src/domain/primitives.ts` | 78 | 19 | 4 |
| `ok` → `pilotOk` | callable value, `src/domain/primitives.ts` | 41 | 8 | 5 |
| `slot_bindings` → `pilot_slot_bindings` | object key, `src/domain/delegated-session.ts` | 29 | 9 | 6 |

Use counts exclude the defining declaration and include other uses in the
defining file. Using-file counts exclude the defining file. The value row
counts callable references and named imports, excluding `Result.ok` fields.
`slot_bindings` includes both JSON definition files and the TypeScript contract,
schema, seed, resolver, and visible tests. This key widens the kind and directory
spread. The exact use-site path lists live in `migrations.py`.

**Limitation:** 11 of the 14 exports in the preliminary eligible pool are
defined in `src/domain/primitives.ts`. The selected migrations therefore
measure ownership effects on widely used symbols from one or two modules,
not migrations generally. The ownership rotation prevents any using directory
from receiving the same ownership group in all four migrations; it cannot
create defining-module diversity absent from the slice.

## Deferred Part 2 check

The Part 2 anchor list is not in this repository. The committed sample
`assay-fixture-manifest/0.2.0` document exercises only path overlap among
`included_paths`, `excluded_paths`, and `FixtureTask.treatment_sites[].path`.
The test remains skipped until the 2b population is frozen. `DoseSite.symbol`
is the caller being treated, not the delegated-to anchor, so this manifest
cannot establish symbol-level overlap.
