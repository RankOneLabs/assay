# Show each session's context-window usage in the inbox

ACP agents report how full their context window is with `usage_update` session updates
(`used` and `size`, both in tokens). kbbl projects these into a session's live event
stream, but it does not keep them, so the inbox and the session list cannot show how full
a session's context is without opening it. Persist the latest report per session and
expose it on the session snapshot and the browser wire.

| Shape | Field | Value |
| --- | --- | --- |
| session snapshot (`AcpSessionSnapshot`, e.g. `getSession`, `listSessions`) | `context_used` | the latest update's `used`, in tokens, or `null` |
| | `context_size` | the latest update's `size`, in tokens, or `null` |
| browser wire (`PwaSessionSnapshot`: the session list and `/inbox` frames) | `contextUsed` | same value as `context_used` |
| | `contextSize` | same value as `context_size` |

Write on every live `usage_update`, with no throttling or debouncing: each one overwrites
the stored pair, including one that lowers it (for example after the agent compacts its
context). A stored value must change the `/inbox` stream like any other session change,
and it must survive a kbbl restart, so keep it in the session's database row. Add a new
migration for the column change rather than editing an existing one.

When kbbl loads a session's history (`session/load`), the agent replays old updates,
which can include old `usage_update`s. Replayed history is not the agent's current state:
a replayed update must not overwrite the stored value.

A session that has never had a live `usage_update` reports `null` in all four fields;
the fields are always present. Existing session, inbox and history behavior must
otherwise stay the same.

The public checks are `bun test ./tests/visible` and
`tsc --noEmit -p tsconfig.json`. The evaluator also runs private feature and
regression checks. Keep the implementation within the existing source tree under
`src/`, which includes the migrations in `src/db/migrations/`. You may add tests of your
own under `tests/agent/`; they are not graded.
