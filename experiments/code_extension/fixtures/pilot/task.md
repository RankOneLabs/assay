# Optional run-context bindings with a declared default

## Background

A workflow definition reads values out of a run's context with
`{ "from": "context", "path": "<JSON pointer>" }` slot bindings. Today every such
binding is mandatory: `resolveBindingValue` fails with
`context pointer '<path>' not found` when the pointer does not resolve, and
`contextRequirementsOf` reports the pointer as a launch requirement, so a launch
whose context lacks it is refused.

Some context keys are genuinely optional — a definition wants "use the
launcher's value if it sent one, otherwise use X" (for example an `effort` that
should fall back to the runtime default, or a notes slot that may be empty).
There is no way to express that today.

## What to build

Let a `context` binding declare a fallback value with an optional `default`
field:

```json
{ "from": "context", "path": "/planner_effort", "default": null }
{ "from": "context", "path": "/brief_notes", "default": "(no notes)" }
```

### Wire schema — `slotBindingSchema` (`src/validation/slot-binding.ts`)

- The `context` variant accepts an optional `default` whose value is a string or
  `null`. Any other JSON type (number, boolean, object, array) is rejected.
- When `default` is present, the parsed binding keeps it, unchanged (including
  `null`). When it is absent, the parsed binding has no `default` key at all —
  the parsed output for existing bindings must be exactly what it is today.
- A `context` binding that declares a `default` must use an absolute JSON
  pointer: `path` must be `""` or start with `/`. Otherwise parsing fails with an
  issue whose message is exactly
  `context binding with a default must use an absolute JSON pointer path`.
  (A `context` binding *without* a default keeps today's rules — its `path` is
  not newly restricted.)
- Only the `context` variant gains `default`. Every other variant keeps its
  current schema exactly (an unexpected `default` key on them is ignored and
  dropped, as unknown keys are today). `bindableSchema` and every stage config
  schema that embeds `slotBindingSchema` must accept the new field wherever a
  slot binding is accepted.

### Domain type — `SlotBinding` (`src/domain/delegated-session.ts`)

The `context` member of the `SlotBinding` union carries the optional field
`readonly default?: string | null`.

### Resolution — `src/compiler/resolve-execution.ts`

`resolveBindingValue(binding, environment)` for a `context` binding:

- If the pointer resolves (to anything, **including `null`**), the resolved
  context value is returned as today — the default never overrides a value the
  launcher actually sent.
- If the pointer does not resolve and the binding declares a `default`, return
  `{ ok: true, value: <default> }` (so `null` for `"default": null`).
- If the pointer does not resolve and there is no `default`, the error is
  unchanged: `{ ok: false, error: { operation: "resolve_execution", detail: "context pointer '<path>' not found" } }`.

Everything built on it must follow: `resolveBinding` (a `null` default renders
as `"null"`, exactly as a `null` context value does today) and
`resolveDelegatedExecution` (a defaulted binding may appear anywhere a binding
may: `slot_bindings`, `fan_out.item_bindings`, `runtime`, `model`, `effort`,
`workdir`, worktree fields — e.g. `effort` with `"default": null` resolves to
`effort: null`).

### Launch requirements — `src/compiler/context-requirements.ts`

- `contextRequirementsOf(graph)` must not report a pointer that is read only
  through defaulted `context` bindings — such a launch can run without it.
- A pointer read by at least one binding *without* a default is still a
  requirement. Deduplication by pointer is unchanged, but the requirement is
  attributed to the first stage (in graph order) that reads it **without** a
  default; a stage that reads it only with a default does not "claim" it.
- `context_lookup` bindings are unchanged.
- `unsatisfiedContextRequirements` and `describeUnsatisfiedRequirements` keep
  their signatures and behaviour.

### End to end

A workflow definition containing defaulted context bindings must pass
`parseWorkflowDefinition` (`src/validation/workflow-definition.ts`) and
`compileWorkflowDefinition` (`src/compiler/compile-workflow.ts`), and the
compiled stage's `executor.definition_config` must still carry each binding's
`default`, so that resolving the compiled stage against a context that lacks the
key uses the default. A definition containing a defaulted binding with a
non-absolute `path` must be rejected by `parseWorkflowDefinition`, and the
returned `error.detail` must contain the message above.

## Compatibility

- Definitions without any `default` behave exactly as before: same parse
  output, same compile output, same resolution results and error messages, same
  context requirements (the shipped `dev_flow_v14` definition's requirement list
  does not change).
- Do not change exported names or signatures other than adding the optional
  field to the `context` member of `SlotBinding`.

## Working in this repository

The repository is a TypeScript project run with Bun. Dependencies are already
installed; there is no network access. You can check your work with:

```
bun test ./tests/visible
tsc --noEmit -p tsconfig.json
```

Both must pass when you are done. You may add tests of your own under
`tests/visible/`, but do not edit `package.json`, `package-lock.json` or
`tsconfig.json`.
