# Add a work-started run-event handler

The existing `projectRunEvent` dispatcher in `src/domain/run-event.ts` handles gate and pull-request operations. Add and register a handler for `work_started` events. Export `projectWorkStartedEvent(row: RunEventRow)` and the `WorkStartedRunEventPayload` interface. The handler must require non-null `run_unit_id` and `work_order_id`, reject a missing value with an Error naming the sequence and operation, and return an event preserving the row's sequence, occurrence time, operation and all existing payload fields. `projectRunEvent` must route `work_started` through that handler so callers receive the same validation. Other operations, including gate and pull-request operations, must keep their existing behavior.

Only `src/domain/run-event.ts` is writable. Do not edit tests, package files or configuration. Public checks: `bun test ./tests/visible` and `tsc --noEmit -p tsconfig.json`. Submit the patch through the extension `submit_output` tool.
