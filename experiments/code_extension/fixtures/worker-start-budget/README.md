# Worker start budget

Subject `oakridge-dbos-worker-start-budget` lets a run's launch configuration set one
agent worker's provider deadline and start budget. It is the library's local control
(survey item D4, control C1), at oakridge `1495ec34`, matched to `worker-silence-bound`.
Both edits sit in `src/domain/`. The launch parser in `run-config.ts` must keep the two
fields. The instruction builder in `effect-instruction.ts` must use them where it uses
`DEFAULT_PROVIDER_DEADLINE_MS` and `DEFAULT_MAX_START_ATTEMPTS` today. The decoder and
every consumer of the instruction already read `deadline_ms` and `max_start_attempts`, so
no edit is needed past the builder.

## Provenance

Cut by `uv run python -m code_extension.slice --scenario worker-start-budget --oakridge
<oakridge>` from oakridge commit `1495ec34`. The slice spec in
`code_extension/library/worker_start_budget.py` is worker-silence-bound's spec, imported
unchanged except for the package name. The repository therefore holds the same files as
that task's, with the same edits made while moving them (see its README). Only
`package.json` and `package-lock.json` differ, and only in the package name.

The repository has 50 files and 479,785 bytes, under the 200-file and 1,000,000-byte
limits.

## Hidden groups

- **Regression:** `kbbl-adapter.test.ts`, the pinned provider and kbbl client tests, as in
  worker-silence-bound. It does not reveal this task's edit, and it could go in the
  visible tests. It stays hidden so that the start tree, and so the visible checks, are
  the same as its pair's. The two tasks then differ only in their request and their hidden
  feature tests.
- **New behavior:** `worker-start-budget.test.ts`, chaining `parseLaunchRequest` →
  `selectEffectInstruction` → `decodeEffectInstruction`, with no database. Titles start
  with `reachability:` when the test fails unless the budget reaches the instruction, and
  `semantics:` otherwise.

## Patches

| Patch | What it does | Should fail |
| --- | --- | --- |
| `reference.patch` | Parses both fields and builds the instruction with them | nothing |
| `unreachable-constants.patch` | Parsed and typed, but the builder still uses the constants | reachability |
| `unreachable-parser.patch` | The builder reads the budget, but the parser drops it | reachability |
| `wrong-stage-wide.patch` | Reaches the instruction, but one worker's budget applies to its whole stage | semantics only |
