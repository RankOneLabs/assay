# Context usage in the inbox

Subject `oakridge-kbbl-context-usage-inbox` keeps each kbbl session's latest
context-window report and shows it in the session list and the `/inbox` stream. It is cut
from oakridge `1495ec34`. Its shape is the code's own: an ACP event arrives in the session
controller, is written by the session store, and flows through the stored row, the session
snapshot and the browser wire. That is a new migration plus four files (`store.ts`,
`types.ts`, `pwa-wire.ts`, `controller.ts`); `/inbox` picks the wire fields up unchanged. One step is not
pointed out by the type checker. The new column, setter, snapshot field and wire field all
type-check without the controller ever calling the setter. The controller's
`handleUpdate` must make that call, and must skip updates replayed by `session/load`.

## Provenance

Cut by `uv run python -m code_extension.slice --scenario context-usage-inbox --oakridge
<oakridge>` from oakridge commit `1495ec34`. The slice spec in
`code_extension/library/context_usage_inbox.py` lists every pinned file and every edit made
while moving it.

kbbl keeps its server code under `kbbl/core/`, with tests beside the code. The slice moves
`kbbl/core/` to `src/` as one block, so no import inside it changes. The migrations
directory becomes `src/db/migrations/`, inside the default writable scope `src/`.

| Fixture path | Source at the pin | Why included |
| --- | --- | --- |
| `src/acp/**`, `src/server/handlers/{acp-inbox,sse-backpressure}.ts` | `kbbl/core/` same paths | The controller, store, types, browser wire and `/inbox` handler the feature passes through, and their import closure |
| `src/{config,runtime}.ts`, `src/session/**`, `src/worktree/service.ts`, `src/pwa/oakridge/operator-contracts.ts` | `kbbl/core/` same paths | Imported by the controller, service and types |
| `src/db/{migrations,test-db}.ts`, `src/db/migrations/00{1,2,3}_*.sql` | `kbbl/core/db/` | The migration runner, the in-memory test database and the schema history |
| `src/acp/{test-harness.ts,__fixtures__/fake-acp-agent.ts}` | `kbbl/core/acp/` | The pinned test service and fake agent the shipped tests use |
| `tests/visible/{store,acp-inbox,migrations}.test.ts` | `kbbl/core/{acp,server/handlers,db}/` | Public checks |
| `package.json`, `package-lock.json` | `integrations/pier/scenario_library/` | The image's dependency lock, renamed |
| `tsconfig.json` | authored | The pinned compiler options, flattened |

The repository has 33 files and 277,267 bytes, under the 200-file and 1,000,000-byte limits.

## Edits made while moving files

- `kbbl/core/` becomes `src/`. Nothing inside it changes.
- Tests move out of the source tree, flat into `tests/visible/`, and their relative imports
  are rewritten to reach `src/`.
- The hidden regression copy of `service.test.ts` imports from `../../../src/acp/`, and
  finds the pinned fake agent at `src/acp/__fixtures__/`.

No production behavior is changed.

## Hidden groups

- **Regression:** `service.test.ts`, the pinned integration tests of the session service,
  controller and fake agent processes (44 tests). It moved out of the visible tests because
  its replay test shows how `handleUpdate` keeps `session/load` history from writing the
  store. That points at the non-local edit the task should make the agent find.
- **New behavior:** `context-usage-inbox.test.ts`, with its own fake ACP agent
  `fake-usage-agent.ts`. The agent is a bun child process that reports `usage_update`, and
  it ships only with this group. A prompt of `usage <used> <size>` sends a report that the
  agent records for replay. A prompt of `compact <used> <size>` sends one it does not record.
  The tests use in-memory SQLite and the service wiring of `makeAcpTestService`, with no
  network. Titles start with `reachability:` when the test fails unless a live report
  reaches the store at all. They start with `semantics:` otherwise: exact values and field
  order, latest-wins, replay, and null when unset.

## Patches

| Patch | What it does | Should fail |
| --- | --- | --- |
| `reference.patch` | Migration 004, row and snapshot fields, store setter, wire fields, and the controller call that skips replay | nothing |
| `unreachable-controller.patch` | Everything but the controller call | reachability (and the semantics tests that need a value) |
| `wrong-replay.patch` | The controller writes replayed updates too | semantics only (the replay test) |
| `swapped-fields.patch` | `used` and `size` are stored in each other's columns | semantics only |
