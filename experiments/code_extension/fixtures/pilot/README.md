# Pilot extension scenario: context binding defaults

This is a study subject, `oakridge-dbos-context-defaults`, using real oakridge-dbos code. It promotes the bounded context-binding feature request previously exercised by the workflow-edit smoke into the extension study's first committed scenario. The source slice is the same pin, so its known-good visible baseline and held-out tests can be checked independently of the new qualification harness. The pilot has one `baseline` arm; later factors can qualify additional arms without changing this tree.

## Provenance

- Source repository: oakridge monorepo, `/home/steve/codes/rol/oakridge`, directory `oakridge-dbos/`.
- Immutable commit: `f3b3ffca43e43672ff2f58ab797d65c7532aaed8`.
- The source material was taken with this exact archive invocation (then selected and adapted as listed below):

  ```sh
  git -C /home/steve/codes/rol/oakridge archive -o slice.tar f3b3ffca43e43672ff2f58ab797d65c7532aaed8 oakridge-dbos/src/domain oakridge-dbos/src/decision oakridge-dbos/src/compiler oakridge-dbos/src/validation oakridge-dbos/src/seed/dev-flow-v14.ts oakridge-dbos/tests workflow-config/definitions/dev_flow_v11.json workflow-config/definitions/dev_flow_v14.json workflow-config/prompts/dev-flow
  ```

- `repository/` has 62 files and 348,954 UTF-8 bytes, within the 200-file and 1,000,000-byte limits. The checked-in `qualification/` records bind the observed runtime image and routing digest at qualification time.

## Included paths

| Fixture path under `repository/` | Pin path | Status |
| --- | --- | --- |
| `src/domain/*.ts` (33 files) | `oakridge-dbos/src/domain/*.ts` | Byte-identical |
| `src/decision/*.ts` (4 files) | `oakridge-dbos/src/decision/*.ts` | Byte-identical |
| `src/compiler/*.ts` (3 files) | `oakridge-dbos/src/compiler/*.ts` | Byte-identical |
| `src/validation/*.ts` (4 files) | `oakridge-dbos/src/validation/*.ts` | Byte-identical |
| `src/seed/dev-flow-v14.ts` | `oakridge-dbos/src/seed/dev-flow-v14.ts` | Adapted: JSON URL depth |
| `workflow-config/definitions/{dev_flow_v11,dev_flow_v14}.json` | Same paths at monorepo root | Byte-identical |
| `workflow-config/prompts/dev-flow/{spec_analyzer_v2,plan_writer_v2,brief_writer,build_v2,assessor_v2}.md` | Same paths at monorepo root | Byte-identical |
| `tests/visible/{compile-workflow,resolve-execution,context-requirements,delegated-session-validation,workflow-definition,dev-flow-stage-contracts,gate-dispositions,wait,artifact-types}.test.ts` | `oakridge-dbos/tests/<same>.test.ts` | Adapted: import depth |
| `tests/visible/decision/{derive.test.ts,snapshot-builder.ts}` | `oakridge-dbos/tests/decision/<same>` | Adapted: import depth |
| `package.json`, `package-lock.json` | `integrations/pier/workflow_edit/` in assay | Adapted toolchain copies: package identity; not from pin |
| `tsconfig.json` | Root and `oakridge-dbos/tsconfig.json` | Adapted: flattened for the slice |

All imports in the source slice resolve within the slice or to `zod` and Node built-ins. The fixed package files supply the image's already installed dependencies; qualification runs no install or fetch.

## Excluded areas

| Pin path | Reason |
| --- | --- |
| `oakridge-dbos/src/storage/**` | Postgres repositories and migrations require a database. |
| `oakridge-dbos/src/http/**` | HTTP surface imports storage and Hono. |
| `oakridge-dbos/src/runtime/**`, `src/workflows/**` | DBOS orchestration and launch paths require excluded services. |
| `oakridge-dbos/src/adapters/**` | Git, HTTP, and runtime integrations fall outside the self-contained domain slice. |
| `oakridge-dbos/src/operators/**`, `src/main.ts`, `src/migrate.ts`, `src/seed/seed-builtins.ts` | Not imported by the selected modules; entry points require excluded services. |
| `oakridge-dbos/src/domain/{run-event,output-release-policy}.test.ts` | Moved to the private hidden regression group because colocated tests otherwise ship to the agent. |
| `oakridge-dbos/tests/support/**`, tests of excluded services, and `tests/architecture.test.ts` | Require Postgres/DBOS or assert over excluded source paths. |
| Other `workflow-config/` definitions and prompts | Not read by the included loader or tests. |
| Root package manifest and `bun.lock` at the pin | Replaced by the fixed image toolchain package files. |

## Adaptations

1. In `src/seed/dev-flow-v14.ts`, the definition URL changes from `../../../workflow-config/` to `../../workflow-config/` because the config directory moves to this repository root.
2. Visible tests move from `oakridge-dbos/tests/` to `tests/visible/`. Their imports of `../src/` become `../../src/`; the two `decision/` imports gain one more `../`. No assertions change.
3. Held-out oakridge regression tests live in `hidden/regression/`, outside the shipped repository. Their imports gain the corresponding relative depth. The two colocated domain tests now import production modules from `tests/hidden/regression/domain/`. The feature checks in `hidden/new_behavior/` were authored for this bounded request and never ship to a worker.
4. `tsconfig.json` flattens the pin's root and package configs. Compiler options remain strict; `include` covers only `src/**/*.ts` and `tests/**/*.ts`, and obsolete `typeRoots` pointing outside the slice are removed so the image's installed types resolve.
5. `package.json` and `package-lock.json` are copied from the pinned Assay runtime toolchain integration, since the full oakridge package requires DBOS, Postgres, and Hono dependencies absent from this slice. Their package identity changes from the smoke fixture's `oakridge-dbos-smoke-edit` to this study subject's `oakridge-dbos-context-defaults`; dependency versions and resolved dependency entries stay the same.

No production function is simplified or stubbed. `patches/reference.patch` is the multi-module correct implementation; `patches/negative.patch` is a partial implementation that accepts and types defaults but omits their resolver and requirement semantics. Both are private qualification assets, never part of `repository/`. The visible group is restored before preflight, followed by `tsc --noEmit -p tsconfig.json`, a bun build, installation of private groups, and all three bun test groups. Only group verdicts are retained; `diagnose.py` replays failures to obtain test names without changing them.

## Reproducing qualification

The qualification command defaults to `~/codes/rol/smithers/routing_config.yaml`, an operator-machine path. On another checkout, pass the local routing file explicitly from the repository root:

```sh
uv run --project experiments python -m code_extension.qualify --routing-config /absolute/path/to/routing_config.yaml --verify-committed
```

The committed manifest binds the routing file's exact bytes as `sha256:1a241e5535f28094ad103e82af57bce52441ec321ebf6cd0013b2773feb4f3f0`. Use a copy with that digest to verify the committed manifest; a different routing file produces a different manifest identity. The pinned runtime image must also be available locally under the qualification command's default image tag (or supply `--image` for an equivalent image with the same observed digest). The command runs the checks without network access or dependency installation.

The Docker replay test accepts `ASSAY_EXTENSION_ROUTING_CONFIG=/absolute/path/to/routing_config.yaml`. It skips replay when the pinned image or routing file is not provisioned, while the committed record and manifest checks still run.
