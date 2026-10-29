# JSON pointer root control

Subject `oakridge-dbos-pointer-root` adds `#` as a spelling for the complete
input value in `readJsonPointer`. It is the study's negative control for graph
navigation: the request is confined to one local utility, needs no nonlocal
registration, and does not require tracing callers. Existing pointer behavior
must remain intact. The public task and visible tests are under `repository/`;
private regression and new-behavior groups and both patches are siblings.

## Provenance and included paths

The source is oakridge-dbos at immutable monorepo commit
`f3b3ffca43e43672ff2f58ab797d65c7532aaed8`. This tree starts from the
pilot's adapted slice of that pin, archived with:

```sh
git -C /home/steve/codes/rol/oakridge archive f3b3ffca43e43672ff2f58ab797d65c7532aaed8 oakridge-dbos/src/domain oakridge-dbos/src/decision oakridge-dbos/src/compiler oakridge-dbos/src/validation oakridge-dbos/src/seed/dev-flow-v14.ts oakridge-dbos/tests workflow-config/definitions/dev_flow_v11.json workflow-config/definitions/dev_flow_v14.json workflow-config/prompts/dev-flow
```

| Included fixture path | Source at pin | Why included |
| --- | --- | --- |
| `src/domain/*.ts`, `src/decision/*.ts`, `src/compiler/*.ts`, `src/validation/*.ts`, `src/seed/dev-flow-v14.ts` | `oakridge-dbos/` equivalents | The established pointer reader and its consumers, plus an existing passing source slice. |
| `tests/visible/**` | Selected `oakridge-dbos/tests/**` | Public baseline regression checks. |
| `workflow-config/definitions/{dev_flow_v11,dev_flow_v14}.json`, `workflow-config/prompts/dev-flow/**` | Same monorepo-root paths | Required by the selected seed and checks. |
| `package.json`, `package-lock.json`, `tsconfig.json` | Pilot runtime-toolchain adaptations | Dependencies and strict TypeScript compilation in the frozen image. |

The repository has 62 files and 348,942 UTF-8 bytes, below the 200-file and
1,000,000-byte limits. It contains no hidden checks or reference patch.

## Excluded paths

| Pin path | Reason |
| --- | --- |
| `oakridge-dbos/src/storage/**`, `src/http/**` | Database and HTTP services are unrelated to the local utility change. |
| `oakridge-dbos/src/runtime/**`, `src/workflows/**`, `src/adapters/**` | DBOS and external integrations require services beyond the slice. |
| `oakridge-dbos/src/operators/**`, `src/main.ts`, `src/migrate.ts`, `src/seed/seed-builtins.ts` | Unused entry points depend on excluded services. |
| Unselected `oakridge-dbos/tests/**`, including support and architecture tests | Exercise excluded services or full-monorepo paths. |
| `oakridge-dbos/src/domain/{run-event,output-release-policy}.test.ts` | Moved to the sibling hidden regression group. |
| Other `workflow-config/**`, root package manifest, and `bun.lock` | Unused or replaced by frozen runtime-toolchain copies. |

## Adaptations and complexity

As in the pilot, source is relocated to `src/`, selected tests to
`tests/visible/`, and only relative imports are adjusted. The seed config URL
moves up one fewer directory; `tsconfig.json` is flattened for the slice.
The pilot's fixed package manifests are reused with only the package identity
changed. Selected regression tests are in sibling `hidden/regression/`, with
relative imports adjusted; the `#` feature checks were authored in sibling
`hidden/new_behavior/`. No production behavior was adapted from the pin.

This scenario has one baseline arm. Its reference patch changes one condition
in `src/domain/json-pointer.ts`. Its negative patch returns null for `#`,
which shows that merely recognizing the new spelling is insufficient. There
is no architectural comparison within this control; its one-file edit is
intentionally less complex than the stage compiler arms. Qualification records
under `qualification/` report baseline, reference, and negative verdicts from
the frozen runtime image. `qualification/manifest.json` binds the tree, task,
patches, and groups to the three retained check records. Its routing digest is
null because the offline checks make no model request.
