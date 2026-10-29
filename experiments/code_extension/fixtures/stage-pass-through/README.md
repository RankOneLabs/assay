# Pass-through stage compiler

Subject `oakridge-dbos-stage-pass-through` asks for one bounded capability:
compile a built-in `pass_through` stage with exactly empty-object configuration,
scalar materialization, immediate output release, and the same executor contract
as existing stage types. The four arms expose the same `task.md`, the same
visible tests, and byte-identical hidden regression and feature groups.

## Provenance and included paths

The source is oakridge-dbos at immutable monorepo commit
`f3b3ffca43e43672ff2f58ab797d65c7532aaed8`. Each arm starts from the
pilot's adapted slice of that pin. The underlying source was archived with:

```sh
git -C /home/steve/codes/rol/oakridge archive f3b3ffca43e43672ff2f58ab797d65c7532aaed8 oakridge-dbos/src/domain oakridge-dbos/src/decision oakridge-dbos/src/compiler oakridge-dbos/src/validation oakridge-dbos/src/seed/dev-flow-v14.ts oakridge-dbos/tests workflow-config/definitions/dev_flow_v11.json workflow-config/definitions/dev_flow_v14.json workflow-config/prompts/dev-flow
```

| Included fixture path in each `repository/<arm>/` | Source at pin | Why included |
| --- | --- | --- |
| `src/domain/*.ts`, `src/decision/*.ts`, `src/compiler/{compile-workflow,context-requirements,resolve-execution}.ts`, `src/validation/*.ts`, `src/seed/dev-flow-v14.ts` | `oakridge-dbos/` equivalents | Compiler contracts, callers, validation, and seed used by checks. |
| `src/compiler/stage-registration.ts` (`cross_module`) | Authored adaptation; absent at pin | Separates the registration contract from the compiler. |
| `src/compiler/stage-plugins.ts` and `src/compiler/stage-plugin-config.json` (`plugin`) | Authored adaptations; absent at pin | Resolve enabled stage types from configuration data. |
| `tests/visible/**` | Selected `oakridge-dbos/tests/**` | Known-good public baseline; assertions are unchanged. |
| `workflow-config/definitions/{dev_flow_v11,dev_flow_v14}.json`, `workflow-config/prompts/dev-flow/**` | Same monorepo-root paths | Seed and public tests load these files. |
| `package.json`, `package-lock.json`, `tsconfig.json` | Pilot runtime-toolchain adaptations | Frozen image dependencies and strict TypeScript compilation. |

Each tree has 62–64 files and 348,960–349,572 UTF-8 bytes, below the 200-file
and 1,000,000-byte package limits. No private check or patch is under any
`repository/` tree.

## Excluded paths

| Pin path | Reason |
| --- | --- |
| `oakridge-dbos/src/storage/**`, `src/http/**` | Database, HTTP, and Hono dependencies are unrelated to compilation. |
| `oakridge-dbos/src/runtime/**`, `src/workflows/**`, `src/adapters/**` | DBOS orchestration and external integrations need services outside the frozen slice. |
| `oakridge-dbos/src/operators/**`, `src/main.ts`, `src/migrate.ts`, `src/seed/seed-builtins.ts` | Unused entry points depend on excluded services. |
| Unselected `oakridge-dbos/tests/**`, including support and architecture tests | Exercise excluded services or assume full monorepo paths. |
| `oakridge-dbos/src/domain/{run-event,output-release-policy}.test.ts` | Moved to `hidden/regression/` so they do not ship to the agent. |
| Other `workflow-config/**`, root package manifest, and `bun.lock` | Unused by the slice or replaced by the frozen image toolchain. |

## Adaptations and arm complexity

The inherited pilot adaptations are: move selected `oakridge-dbos` source to
`src/`, visible tests to `tests/visible/`, adjust only their relative imports,
flatten `tsconfig.json` for that layout, and shorten the seed's config URL by
one directory. The package files come from the pilot's pinned image-toolchain
copy; only their package identity changes to this subject. The two colocated
domain tests and the other selected regression tests are moved to sibling
`hidden/regression/` with import depths corrected. The new feature test was
authored for this request in sibling `hidden/new_behavior/`.

| Arm | Baseline adaptation from the pin | Reference edit and complexity difference |
| --- | --- | --- |
| `modular` | Existing compiler object registry; no dispatch rewrite. | Add one compiler object and one registration entry in a single file. |
| `central` | Replace the built-in registry lookup with a central switch, preserving explicitly injected registries. | Add the compiler and a switch case; the central selector is a coupled edit point. |
| `cross_module` | Move built-in registration into `stage-registration.ts`, receiving compiler objects from the compiler module. | Add the compiler in one module and its registration parameter and entry in another; requires following a nonlocal contract. |
| `plugin` | Put enabled stage names in `stage-plugin-config.json`, resolved by `stage-plugins.ts` against available compiler objects. | Add the compiler to the available set and enable it in data; requires following the loader and config. |

These differences affect edit count and navigation distance, so architecture
is not the only possible explanation for an arm result. The per-arm reference
patches express the intended behavior; each negative patch defines a compiler
but omits its dispatch registration. All patches are private siblings of the
repository trees. The qualification records under `qualification/` report the
three group verdicts for baseline, reference, and negative runs against the
frozen runtime image. The `qualification/manifest.json` arm records bind each
tree, task, patch, and frozen group to the three retained check records. Its
routing digest is null because the offline checks make no model request.
