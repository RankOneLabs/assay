# Cross-module event candidate — upstream feasibility established

Status: **feasible at the upstream pin, not frozen or qualified**. This is a review draft and must not be offered to an agent or included in a pilot manifest.

Extend the run-event pipeline with a new cross-module event. A real producer must emit it, a real consumer must handle it, and the public event type must include it. Serialization and validation must retain the row's sequence, occurrence time, and payload fields. Existing gate, pull-request, and work-started event behavior must remain compatible. The implementation must require linked schema, producer, consumer, and export changes. The new operation and payload contract still need to be fixed before this becomes a frozen task.

Requested implementation scope: `src/domain/run-event.ts`, `src/storage/postgres-operators.ts`, `src/http/invalidation-events.ts`, and `src/http/app.ts`. The pin exports `RunEvent` from `run-event.ts`; `PostgresOperatorProjectionRepository.list_run_events` produces projected rows through an injected `SqlExecutor`, `createInvalidationEventApp` consumes events through injected callbacks, and `app.ts` wires that consumer to the repository. Tests, dependency files, and configuration files would be protected. Public checks would be `bun test ./tests/visible` and `tsc --noEmit -p tsconfig.json`; submission would use `submit_output`. A fresh pin extraction of root `tsconfig.json`, all `oakridge-dbos/src`, `tests/invalidation-events.test.ts`, `package.json`, and package `tsconfig.json` contains these paths (125 files, 706,674 bytes before dependency installation); the existing upstream `hono` dependency must be locked for the HTTP tests. The injected SQL query seam permits producer tests without Postgres.

## Requirements to intended hidden assertions

| Intended assertion | Public requirement or prior behavior | Status at upstream pin |
| --- | --- | --- |
| End-to-end event handling | Emit the new event from the real producer and handle it in the real consumer. | Producer, consumer, and app wiring exist. |
| Serialization and validation | `projectRunEvent` validates and preserves the new event's fields. | Projector exists. |
| Public export | `RunEvent` includes the new event and its payload type. | Export exists in `run-event.ts`. |
| Existing event compatibility | Gate, pull-request, and work-started behavior remains unchanged. | Existing projection behavior is present. |

No hidden tests or patches have been authored for this unfrozen candidate.
