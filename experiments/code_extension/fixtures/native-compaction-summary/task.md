# Use the agent's native compaction summary as the session handoff

When a kbbl session closes, kbbl stores a terminal summary that later stands in for the
transcript. Today it tries a manual `/compact` turn first and falls back to the final
assistant response. The `native_compaction` summary method is declared, but nothing
produces it.

ACP agents can compact their own context and report it with two session updates:
`compaction_update` (a compaction's lifecycle, identified by `compactionId`, with status
`in_progress`, `completed`, `failed` or `cancelled`) and `compaction_summary_chunk`
(a piece of that compaction's summary, streamed while it is in progress). An agent sends
these only to a client that advertises compaction support when it initializes. kbbl
advertises nothing, and drops these updates if they arrive.

Make the agent's own compaction the session handoff:

- Advertise compaction support to the agent, as the ACP SDK in the dependency lock
  defines it.
- Project these updates into kbbl's UI event union instead of dropping them, so a
  session's events record its completed compactions.
- Add a summary generator `NativeCompactionSummaryGenerator`, exported from
  `src/acp/session-summary.ts`, whose `method` is `"native_compaction"`. It implements
  `SessionSummaryGenerator`, and like the existing generators it returns a draft with
  `schema_version: 1`, the request's `session_id` and `produced_at`, and the summary text
  as `markdown`.
- By default, kbbl tries native compaction first, then manual `/compact`, then the final
  response.

Which compaction counts, and which text it contributes:

- Only the latest compaction that **completed** during the final turn (after the last user
  message) counts. Compactions that failed, were cancelled or never finished produce no
  native summary, and neither does a compaction from an earlier turn. When there is none,
  the generator fails and the next strategy runs.
- The `summary` carried on the `completed` `compaction_update` is authoritative: when
  present, it replaces anything streamed for that compaction. When the completed update
  carries no summary, the handoff is the `compaction_summary_chunk` content streamed for
  that same `compactionId`, in order. Chunks of any other compaction are never part of it.
- The markdown is the text of those content blocks joined with no separator and trimmed,
  as the final-response generator does for message chunks. If it is empty, the generator
  fails.

Other update kinds keep their current projection, and updates kbbl does not know still
project to `null`. Existing session, store and summary behavior must otherwise stay the
same.

The public checks are `bun test ./tests/visible` and
`tsc --noEmit -p tsconfig.json`. The evaluator also runs private feature and
regression checks. Keep the implementation within the existing source tree. You
may add tests of your own under `tests/agent/`; they are not graded.
