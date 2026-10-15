# smoke-edit fixture

A **throwaway** qualification fixture for the workflow-edit study. It exists to
exercise the run path end to end (bounded multi-turn agent loop on local
Qwen2.5-Coder-32B, patch capture, hidden-test correctness evaluation) and to
measure token, time and footprint numbers on a real multi-file edit of real
code. It is **never a study subject**, and nothing measured on it is a study
result.

## Provenance

- Source: oakridge-dbos (oakridge monorepo, `/home/steve/codes/rol/oakridge`) at
  immutable commit **`f3b3ffca43e43672ff2f58ab797d65c7532aaed8`**.
- Files were taken with
  `git -C /home/steve/codes/rol/oakridge archive f3b3ffca43e43672ff2f58ab797d65c7532aaed8 <paths>`
  and placed by a one-off assembly script (not committed; it only copied files
  and applied the path adaptations listed below).
- `repository/` holds **62 files, 348,936 bytes** (limits: < 200 files,
  < 1,000,000 bytes).

### Included paths (`repository/`)

| fixture path | pin path | status |
|---|---|---|
| `src/domain/*.ts` (33 files) | `oakridge-dbos/src/domain/*.ts` | byte-identical; every non-test file in the directory |
| `src/decision/*.ts` (4 files) | `oakridge-dbos/src/decision/*.ts` | byte-identical; whole directory |
| `src/compiler/*.ts` (3 files) | `oakridge-dbos/src/compiler/*.ts` | byte-identical; whole directory |
| `src/validation/*.ts` (4 files) | `oakridge-dbos/src/validation/*.ts` | byte-identical; whole directory |
| `src/seed/dev-flow-v14.ts` | `oakridge-dbos/src/seed/dev-flow-v14.ts` | **adapted** (one line, see below) |
| `workflow-config/definitions/dev_flow_v11.json`, `dev_flow_v14.json` | `workflow-config/definitions/…` (monorepo root) | byte-identical |
| `workflow-config/prompts/dev-flow/{spec_analyzer_v2,plan_writer_v2,brief_writer,build_v2,assessor_v2}.md` | `workflow-config/prompts/dev-flow/…` | byte-identical (the five templates `dev_flow_v14` references) |
| `tests/visible/{compile-workflow,resolve-execution,context-requirements,delegated-session-validation,workflow-definition,dev-flow-stage-contracts,gate-dispositions,wait,artifact-types}.test.ts` | `oakridge-dbos/tests/<same>.test.ts` | **adapted** (import prefix only) |
| `tests/visible/decision/{derive.test.ts,snapshot-builder.ts}` | `oakridge-dbos/tests/decision/…` | **adapted** (import prefix only) |
| `package.json`, `package-lock.json` | — | byte-identical copies of `integrations/pier/workflow_edit/package.json` / `package-lock.json` (verified with `cmp`) |
| `tsconfig.json` | flattening of root `tsconfig.json` + `oakridge-dbos/tsconfig.json` | written for the fixture (see below) |

The slice depends only on itself, `zod` and `node:crypto` (`src/decision/ids.ts`)
— checked by listing every import in the four directories.

### Excluded areas and why

| pin path | reason |
|---|---|
| `src/storage/**` (incl. migrations) | Postgres (`pg`) repositories, SQL executor, migrations — needs a database |
| `src/http/**` | hono HTTP surface; also imports `storage/` |
| `src/runtime/**` | DBOS launch client, git/GitHub runners, executor registry; imports `storage/`/DBOS |
| `src/workflows/**` | DBOS workflow topology |
| `src/adapters/**` | executor adapters talking to kbbl over HTTP and to git; `repository-provisioning.ts` imports `runtime/keyed-mutex` |
| `src/operators/select-status.ts` | outside the four chosen directories and unused by them (it imports only domain types, so it could have been included); left out to keep the slice to `domain`/`decision`/`compiler`/`validation` plus the one seed loader the tests need |
| `src/main.ts`, `src/migrate.ts` | process entry points (DBOS, Postgres) |
| `src/seed/seed-builtins.ts` | imports `storage/repositories` |
| `src/domain/output-release-policy.test.ts`, `src/domain/run-event.test.ts` | not dropped: **moved** into the hidden regression group (colocated tests would otherwise sit in `src/` where `bun test ./tests/visible` never runs them) |
| `tests/support/**` and every test importing `storage/`, `http/`, `runtime/`, `workflows/`, `adapters/`, `operators/` or `tests/support` (postgres-*, run-record-*, dev-flow-e2e, migrate, session-hold, launch-run, …) | need Postgres/DBOS or excluded modules |
| `tests/architecture.test.ts` | asserts over the whole `src/` tree (including excluded `storage/` files); meaningless on a slice |
| `tests/prompt-template.test.ts`, `project-identity.test.ts` | test excluded `runtime/` modules |
| `workflow-config/` other definitions and prompts | not read by any included code or test |
| oakridge `package.json` / `bun.lock` | replaced by the fixed toolchain package files (DBOS, hono, pg are not installed) |

### Adaptations (each one, and why)

1. **`src/seed/dev-flow-v14.ts`** — `new URL("../../../workflow-config/definitions/dev_flow_v14.json", import.meta.url)`
   → `new URL("../../workflow-config/definitions/dev_flow_v14.json", import.meta.url)`.
   At the pin the JSON sits at the monorepo root, one level above
   `oakridge-dbos/`; in the fixture `workflow-config/` sits at the repository
   root. Nothing else in the file changed.
2. **Visible tests moved from `tests/` to `tests/visible/`** (required layout) —
   every `from "../src/` became `from "../../src/` (and in
   `tests/visible/decision/*`, `from "../../src/` became `from "../../../src/`).
   No other byte changed. The tests' own `new URL("../../workflow-config/…", import.meta.url)`
   reads needed no change: one directory deeper inside a repository whose root
   now holds `workflow-config/` resolves to the same files.
3. **Hidden regression copies of real tests** — the same import-prefix rewrite
   for their deeper location (`tests/hidden/regression/`: `../src/` →
   `../../../src/`; the two colocated domain tests: `./run-event`,
   `./compiled-workflow`, `./output-release-policy` →
   `../../../../src/domain/…`). No other byte changed.
4. **`tsconfig.json`** — self-contained flattening of the pin's root
   `tsconfig.json` and `oakridge-dbos/tsconfig.json`: same `compilerOptions`
   (ESNext target/module, `moduleResolution: bundler`, `strict`,
   `noImplicitOverride`, `noUnusedLocals`, `noUnusedParameters`,
   `esModuleInterop`, `skipLibCheck`, `resolveJsonModule`, `allowJs: false`,
   `allowImportingTsExtensions`, `jsx: react-jsx`, `types: ["bun"]`,
   `lib: ["ESNext", "DOM"]`), `include: ["src/**/*.ts", "tests/**/*.ts"]`.
   Dropped: the kbbl/lbc-dashboard `include`/`exclude` entries and **all
   `typeRoots`** (both configs pointed at `node_modules/@types` dirs that do not
   exist here); default typeRoots walk up the ancestors to the image's
   `/node_modules/@types`, which is where `@types/bun` lives.

No production function was simplified or stubbed.

## The task (`task.md`)

**Optional run-context bindings with a declared default.** A
`{ from: "context", path }` slot binding may carry `default: string | null`.
Required coordinated changes:

- `src/validation/slot-binding.ts` — schema accepts and preserves `default`
  (string or null only), keeps no `default` key when absent, and rejects a
  defaulted binding whose `path` is not `""`/`/…` with the exact message
  `context binding with a default must use an absolute JSON pointer path`.
- `src/domain/delegated-session.ts` — `SlotBinding`'s context member gains
  `readonly default?: string | null` (needed for the resolver to typecheck).
- `src/compiler/resolve-execution.ts` — `resolveBindingValue` falls back to the
  default only when the pointer does not resolve (a context `null` wins).
- `src/compiler/context-requirements.ts` — a defaulted binding is no launch
  requirement; a pointer is attributed to the first stage reading it *without*
  a default.

The end-to-end path (`parseWorkflowDefinition` → `compileWorkflowDefinition` →
`resolveDelegatedExecution`) only works if the schema change is made, because
zod strips unknown keys: an implementation that edits only the resolver and the
type passes `tsc` but loses `default` at parse time.

Design notes:

- Not built on any reserved anchor: neither patch touches
  `domain/output-release-policy.ts`, `domain/workflow-recovery.ts` or
  `decision/derive.ts`, and the task asks for no change to release policy,
  fan-out input handling (`stageInputs`/`isReady`/`selectInputsForUnit`),
  materialization diagnostics (`parseUnit`/`findCycle`) or recovery
  classification. (`derive.ts`'s `mintUnits` calls the shared
  `resolveBindingValue` for `fan_out.over`; it inherits the new semantics
  without being edited, and no test exercises a defaulted `over`.)
- Traps that separate careful from careless solutions: `null` in the context vs.
  absent; the absent-`default` parse output must keep exactly two keys; the
  first-stage attribution rule; the definition-time rejection message; defaults
  in every binding position (runtime/model/effort/workdir/worktree/item
  bindings).
- Size: the reference touches 5 production files (~40 changed lines). A
  competent engineer needs well under an hour; a 32B model needs to find four
  modules and make them agree, which should give a mix of outcomes in ≤ 20 turns.

## Hidden tests

The evaluator applies the candidate patch to a copy of `repository/`,
typechecks the candidate tree (`tsc --noEmit -p tsconfig.json`), then copies
each group into the repository root at its path relative to `hidden/<group>/`
and runs it:

| group | files land at | run with |
|---|---|---|
| regression | `tests/hidden/regression/**` | `bun test ./tests/hidden/regression` |
| new_behavior | `tests/hidden/new-behavior/**` | `bun test ./tests/hidden/new-behavior` |

None of these paths exist in `repository/`.

- **`hidden/regression/`** (53 tests, 7 files): held-out real oakridge tests
  that exercise only the slice — `cohort-pull-request`, `final-pull-request`,
  `operator-projections`, `workflow-recovery`, `domain/run-event`,
  `domain/output-release-policy` (import prefixes adapted, see above) — plus
  `context-binding-compat.test.ts`, new compatibility cases pinned at the
  checkpoint: no-default bindings parse to exactly `{from, path}`, keep the
  permissive path rule, still fail with `context pointer '<path>' not found`,
  still count as launch requirements; stray `default` keys on other variants
  are dropped; the shipped `dev_flow_v14` compiles with unchanged bindings.
- **`hidden/new_behavior/`** (26 tests, 1 file):
  `context-binding-default.test.ts` — schema acceptance/rejection and exact
  message, `resolveBindingValue`/`resolveBinding` fallback vs. present value
  (including `null`), `resolveDelegatedExecution` defaults in every position,
  `contextRequirementsOf` exclusion and attribution, and the end-to-end
  parse → compile → resolve path plus definition-time rejection.

Hidden tests are valid TypeScript against the reference (checked: `tsc` passes
with both groups copied into the reference tree, and into the negative tree).
Against the unmodified repository they do not typecheck (they write
`default` into `SlotBinding` literals); the evaluator does not typecheck them.

## Patches

Both are plain-text `git diff`-format patches applying with `git apply` at the
`repository/` root. Neither touches `package.json`, `package-lock.json`,
`tsconfig.json` or any test file.

- `patches/reference.patch` (sha256 `28536da50f0a0d414c3a7a31e00bc840cf6f6f5cc7c10c2dd127b460cb3084f9`) —
  touches `src/compiler/context-requirements.ts`,
  `src/compiler/resolve-execution.ts`, `src/domain/delegated-session.ts`,
  `src/domain/json-pointer.ts`, `src/validation/slot-binding.ts`. Names the
  context member (`ContextSlotBinding`) with its contract documented once;
  adds `isAbsoluteJsonPointer` to `json-pointer.ts` and uses it both in
  `readJsonPointer` and in the schema refinement, so "a pointer that can
  resolve" has one definition; the resolver falls back in the single
  `context` branch of `resolveBindingValue` that every consumer goes through;
  context-requirements reads `default` off the **schema-parsed** binding,
  keeping its "recognise a binding by its own schema" design.
- `patches/negative.patch` (sha256 `f4a41575fc1202c7defdbe8f7ae1209bcd607c901734cfe1be61fda33651f4e2`) —
  correct (passes everything) but messy. Concretely:
  1. **The fallback rule is written twice in the resolver.** Once in
     `resolveBindingValue` (re-checking `typeof default === "string" || === null`
     inline, with a cast) and again in `resolveBindable`, which re-reads the
     pointer and short-circuits before calling `resolveBindingValue` — a
     second copy of the policy that must be kept in sync, and a double pointer
     read for runtime/model/effort/worktree fields.
  2. **context-requirements sniffs raw JSON instead of using the schema.**
     `walkConfig` gets an ad-hoc `raw.from === "context" && hasOwnProperty(raw, "default") && (string | null)`
     check ahead of `contextPointersOf`, duplicating the schema's type rule by
     hand and bypassing the module's documented principle that a binding is
     recognised by `slotBindingSchema`. It also silently diverges: it does not
     apply the absolute-path rule, so it treats as "optional" a binding the
     schema refuses.
  3. **The absolute-pointer rule is re-implemented inline**
     (`path !== "" && path[0] !== "/"`) in the schema rather than shared with
     `readJsonPointer`, which carries its own copy of the same condition.
  4. The domain type is edited inline in the union with no documentation of
     the "context null wins" contract.

## Verification performed

Toolchain: image `assay-pier-bridge:wf13-dev` (bun 1.3.13, tsc 5.9.3,
`/node_modules` with zod 4.4.3, typescript 5.9.3, @types/bun 1.3.13). Scratch
copies lived under `smoke-edit/.scratch/{base,ref,neg}` (deleted afterwards).
Patches were applied with `git -C <copy> apply --verbose patches/<name>.patch`
to fresh copies of `repository/` (in the session scratchpad, outside any git
repository), all hunks reported "Applied patch … cleanly", and the patched trees
were copied into `.scratch/` for Docker. For each tree `<T>`:

```
docker run --rm --network none -u 1000:1000 -v <T>:/workspace -w /workspace --entrypoint tsc assay-pier-bridge:wf13-dev --noEmit -p tsconfig.json
docker run --rm --network none --read-only --tmpfs /tmp -u 1000:1000 -v <T>:/workspace -w /workspace --entrypoint bun assay-pier-bridge:wf13-dev test ./tests/visible
# then: cp -r hidden/regression/. <T>/ ; cp -r hidden/new_behavior/. <T>/
docker run --rm --network none --read-only --tmpfs /tmp -u 1000:1000 -v <T>:/workspace -w /workspace --entrypoint bun assay-pier-bridge:wf13-dev test ./tests/hidden/regression
docker run --rm --network none --read-only --tmpfs /tmp -u 1000:1000 -v <T>:/workspace -w /workspace --entrypoint bun assay-pier-bridge:wf13-dev test ./tests/hidden/new-behavior
```

| tree | `tsc --noEmit` (before hidden copy) | `bun test ./tests/visible` | `./tests/hidden/regression` | `./tests/hidden/new-behavior` |
|---|---|---|---|---|
| baseline (unmodified) | exit 0 | 86 pass / 0 fail (10 files) | 53 pass / 0 fail (7 files) | **5 pass / 21 fail** (exit 1) |
| reference.patch | exit 0 | 86 pass / 0 fail | 53 pass / 0 fail | 26 pass / 0 fail |
| negative.patch | exit 0 | 86 pass / 0 fail | 53 pass / 0 fail | 26 pass / 0 fail |

Baseline new-behavior failures are all runtime assertion failures
(`expect(received).toEqual(expected)` / `toBe`) for the unmet requirement —
e.g. the schema strips `default`, the resolver reports
`context pointer '…' not found`, `contextRequirementsOf` still lists defaulted
pointers, and `parseWorkflowDefinition` accepts a relative defaulted path. The 5
baseline passes are cases that hold either way (a present context value wins;
context `null` is a value; a mandatory read in the same stage still counts; an
empty-path defaulted binding is accepted).

Additional checks: `tsc --noEmit -p tsconfig.json` exits 0 on the reference and
negative trees with both hidden groups copied in; `cmp` confirms
`repository/package.json` and `package-lock.json` are identical to
`integrations/pier/workflow_edit/`; `diff -rq` against the pin confirms every
file under `repository/src` and `repository/workflow-config` is byte-identical
except `src/seed/dev-flow-v14.ts`.
