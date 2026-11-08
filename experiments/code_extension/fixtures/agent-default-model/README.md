# Agent default model

Subject `oakridge-kbbl-agent-default-model` lets an agent entry in kbbl's config declare
the model and effort a new session requests when its request names none, and reports them
on `/config`. It is survey item K4, cut from oakridge `1495ec34`. Its shape is the code's
own, and the existing `session_mode` field shows the whole path: a config schema field
(`config.ts`), copied onto the agent profile (`acp/agent-profile.ts`), read by the session
service (`acp/session-service.ts`) and reported by an HTTP route (`server/app.ts`). The step
the type checker does not point out is that the service starts new sessions in two places.
`createSession` serves the browser. `ensureResumableSession` serves Oakridge's DBOS
workers, and it builds its own session row. A default filled in only one of them leaves the
other path requesting nothing.

## Provenance

Cut by `uv run python -m code_extension.slice --scenario agent-default-model --oakridge
<oakridge>` from oakridge commit `1495ec34`. The slice spec in
`code_extension/library/agent_default_model.py` lists every pinned file and every edit
made while moving it.

| Fixture path | Source at the pin | Why included |
| --- | --- | --- |
| `src/**` | `kbbl/core/**`, the import closure of `config.ts`, `acp/agent-profile.ts`, `acp/session-service.ts` and `server/app.ts` | The code the feature passes through |
| `src/acp/test-harness.ts`, `src/acp/__fixtures__/fake-acp-agent.ts` | same paths under `kbbl/core/` | The pinned test harness and the fake ACP agent it launches (models `fake-small`/`fake-large`, efforts `low`/`high`) |
| `src/db/migrations/*.sql` | `kbbl/core/db/migrations/` | Read at run time by `openTestDb` |
| `oakridge-dbos/src/http/{routes,control-auth,browser-write-policy,errors}.ts`, `oakridge-dbos/src/core-client/core-types.ts` | same paths | Imported by kbbl's Oakridge proxy handler, which `server/app.ts` mounts |
| `tests/visible/config.test.ts` | `kbbl/core/config.test.ts` | Public checks |
| `tests/visible/app.test.ts` | `kbbl/core/server/app.test.ts` | Public checks, including `GET /config` against a stub service |
| `tests/visible/sessions.model.test.ts` | `kbbl/core/server/handlers/sessions.model.test.ts` | Public checks, including resume inheritance of model and effort |
| `package.json`, `package-lock.json` | `integrations/pier/scenario_library/` | The image's dependency lock, renamed |
| `tsconfig.json` | authored | The pinned compiler options, flattened |

The repository has 69 files and 523,683 bytes, under the 200-file and 1,000,000-byte limits.
The survey estimated 60 files and 486 KB. The difference is the three shipped tests, the
test harness with its fake agent and worktree provider, and the migration files. Nothing
is trimmed from the import closure, because every file in it is needed for `server/app.ts`
to type-check.

## Edits made while moving files

- `kbbl/core/` ships as `src/`, so the agent's writable scope is `src/`, as in the other
  library tasks. `oakridge-dbos/src/` keeps its own path, so the proxy handler's
  `../../../../oakridge-dbos/` imports become `../../../oakridge-dbos/`.
- The three visible tests ship flat in `tests/visible/`, and their relative imports are
  rewritten to `../../src/...`.
- One pinned test in `app.test.ts`, `GET /directories > rejects paths outside allowed
  roots`, is marked `test.skip`. It needs a temporary directory outside `HOME`, and the
  evaluator's sandbox sets `HOME=/tmp`, which makes every temporary directory an allowed
  root. It has nothing to do with the feature.
- The hidden regression copy of `service.test.ts` imports from `../../../src/acp/...`, and
  launches the fake agent from `src/acp/__fixtures__/`.

No production behavior is changed. The fake agent is the pinned fixture, unchanged. No
fake agent is authored for this task.

## Hidden groups

- **Regression:** `service.test.ts`, the pinned integration tests of the session service
  against the fake agent. It moved out of the visible tests because its session-mode tests
  run the profile's start setting through `ensureResumableSession`. That points at the
  second create path the task should make the agent find.
- **New behavior:** `agent-default-model.test.ts`. Profiles come from
  `loadAgentProfiles(KbblConfigSchema.parse(...).acp)`, and the service is composed the way
  `server.ts` composes it, with real SQLite and the fake agent. `/config` is checked through
  `createApp` over that service. Titles start with `reachability:` when the test fails
  unless the default reaches the session on its normal path, and `semantics:` otherwise.

## Patches

| Patch | What it does | Should fail |
| --- | --- | --- |
| `reference.patch` | Declares the defaults, carries them on the profile, fills them in on both create paths, and reports them on `/config` | nothing |
| `unreachable-ensure.patch` | Everything except the ensure path, so only `createSession` applies the defaults | reachability |
| `wrong-precedence.patch` | Both paths apply the defaults, but over a model or effort the request names or inherits | semantics only |
