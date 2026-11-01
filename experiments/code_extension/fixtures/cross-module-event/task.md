# Carry an invalidated output slot through the run-event pipeline

`slot_invalidated` is already a run-transition operation, but the run-event pipeline treats it as an ordinary operation with no invariants: nothing validates it, the projection drops the revision that superseded the slot, and the event stream announces it like any other. Give it the same first-class treatment the gate and pull-request operations already have, end to end.

Export a `SlotInvalidatedRunEventPayload` interface and a `SlotInvalidatedRunEventDetail` type from `src/domain/run-event.ts`, and include the operation in the exported `RunEvent` union with that payload. The payload must require a non-null `run_unit_id` and `output_name`, must require a `detail` carrying a string `invalidation_kind`, and must expose `superseded_by` — the artifact revision that replaced the invalidated slot, or `null` when nothing replaced it. `projectRunEvent` must reject a `slot_invalidated` row that is missing any required field with an Error naming the sequence and the operation, and must otherwise return an event preserving the row's sequence, occurrence time and existing payload fields.

The superseding revision has to reach consumers, so the producer must supply it: `PostgresOperatorProjectionRepository.list_run_events` in `src/storage/postgres-operators.ts` must select it alongside the row's other columns. And the stream must name it: `createInvalidationEventApp` in `src/http/invalidation-events.ts` must announce an invalidated slot on its own `slot_invalidated` server-sent event rather than the generic `run_event` frame, so a client can drop the affected output without inspecting every event's operation.

Gate, pull-request and every other operation must keep their existing behavior, including their existing validation and their existing frame name.

`src/domain/`, `src/storage/` and `src/http/` are writable. Do not edit tests, package files or configuration. Public checks: `bun test ./tests/visible` and `tsc --noEmit -p tsconfig.json`. Submit the patch through the extension `submit_output` tool.
