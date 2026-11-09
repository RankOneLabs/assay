# Native compaction summary

Subject `oakridge-kbbl-native-compaction-summary` makes an ACP agent's own context
compaction the terminal handoff of a kbbl session (survey item K1). It is cut from
oakridge `1495ec34`. Its shape is the code's own: a protocol capability, a projector
case, a new event kind, and a strategy in an ordered default list. Two steps are not
pointed out by the type checker. The client must advertise compaction at `initialize`
(`clientCapabilities: {}` today), or a compliant agent never sends the updates. The
service's default generator list must put the new generator first, because the
final-response fallback answers for almost every session.

## Provenance

Cut by `uv run python -m code_extension.slice --scenario native-compaction-summary
--oakridge <oakridge>` from oakridge commit `1495ec34`. The slice spec in
`code_extension/library/native_compaction_summary.py` lists every pinned file and every
edit made while moving it.

| Fixture path | Source at the pin | Why included |
| --- | --- | --- |
| `src/acp/**` | `kbbl/core/acp/**`, the import closure of the client, projector, summary generators and session service | The code the feature passes through |
| `src/{config,runtime}.ts`, `src/session/**`, `src/pwa/oakridge/operator-contracts.ts` | `kbbl/core/` same paths | Imported by the session service, store and types |
| `src/db/{migrations,test-db}.ts`, `src/db/migrations/00{1,2,3}_*.sql` | `kbbl/core/db/` same paths | The in-memory SQLite database the store tests and hidden tests open |
| `tests/visible/{client,resume-context,session-summary,store}.test.ts` | `kbbl/core/acp/` colocated tests | Public checks |
| `package.json`, `package-lock.json` | `integrations/pier/scenario_library/` | The image's dependency lock, renamed; it pins `@agentclientprotocol/sdk` 1.4.0, as kbbl does |
| `tsconfig.json` | authored | The pinned compiler options, flattened |

The repository has 29 files and 244,937 bytes, under the 200-file and 1,000,000-byte
limits.

## Edits made while moving files

- kbbl's `core/` directory becomes `src/`, so `kbbl/core/acp/client.ts` is
  `src/acp/client.ts`. Every relative import inside the slice is unchanged, and the
  default writable scope `src/` covers every edit.
- The colocated tests move to `tests/visible/`, so `./x` becomes `../../src/acp/x` and
  `../db/test-db` becomes `../../src/db/test-db`.
- kbbl's own fake ACP agent and test harness are not shipped. No shipped test uses them,
  and the hidden end-to-end test builds its service directly.

No production behavior is changed.

## Hidden groups

- **Regression:** `transforms.test.ts`, the pinned projector and profile tests. It moved
  out of the visible tests because it asserts that a `compaction_update` projects to
  `null`, which points at the projector edit. The feature gives that update a projection,
  so its null case now uses an unknown update type instead; every other assertion is as
  pinned. It passes at the start tree and under the reference.
- **New behavior:** `native-compaction-summary.test.ts`, plus `compacting-agent.ts`, a
  fake ACP agent process modelled on kbbl's `__fixtures__/fake-acp-agent.ts`. The agent
  compacts during every prompt (in progress, one draft chunk, then completed with the
  authoritative summary), but only when `initialize` advertised
  `clientCapabilities.session.compaction`. It ships only in this group (survey decision 5).
  - `reachability:` tests run a session against the fake agent over in-memory SQLite and a
    bun child process, close it, and read the stored summary's method: one with an ordinary
    prompt, one with `/compact`. They fail unless the capability is advertised and the default
    list reaches the new generator before the manual and final-response ones. A `semantics:`
    test checks the stored text from the same path.
  - `semantics:` tests project ACP updates through `projectSessionUpdate` and run the new
    generator directly, so they do not depend on the event shape the attempt chooses:
    summary over chunks, chunks of the completed compaction only, failed, cancelled and
    unfinished compactions, the latest completion, and an earlier turn's compaction.

## Patches

| Patch | What it does | Should fail |
| --- | --- | --- |
| `reference.patch` | Advertises compaction, projects completed compactions and chunks, adds the generator first in the default list | nothing |
| `unreachable-capability.patch` | Everything except the capability, so the agent never sends compaction updates | reachability |
| `unreachable-order.patch` | The generator is appended after the final-response fallback | reachability |
| `wrong-chunks-across-ids.patch` | Without a summary on the completed update, joins the chunks of every compaction in the turn | semantics only |
| `wrong-unfinished-compaction.patch` | Projects every compaction status, so a failed or unfinished compaction's chunks become the handoff | semantics only |
