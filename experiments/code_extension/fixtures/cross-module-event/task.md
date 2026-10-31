# Cross-module event candidate — blocked before fixture extraction

Status: **not frozen or qualified**. This preserves the requested public contract for review; it must not be offered to an agent or included in a pilot manifest.

Extend the run-event pipeline with a new cross-module event. A real producer must emit it, a real consumer must handle it, and the public event type must include it. Serialization and validation must retain the row's sequence, occurrence time, and payload fields. Existing gate, pull-request, and work-started event behavior must remain compatible. The implementation must require linked schema, producer, consumer, and export changes. The operation name and producer and consumer APIs cannot be specified faithfully until a source slice containing those integration points is selected.

Requested implementation scope: the existing event schema, producer, consumer, and public export modules. Tests, dependency files, and configuration files would be protected. Public checks would be `bun test ./tests/visible` and `tsc --noEmit -p tsconfig.json`; submission would use `submit_output`. Exact producer and consumer API names and paths cannot be frozen because those modules do not exist in the pinned slice.

## Requirements to intended hidden assertions

| Intended assertion | Public requirement or prior behavior | Status in pinned slice |
| --- | --- | --- |
| End-to-end event handling | Emit the new event from the real producer and handle it in the real consumer. | Producer and consumer absent. |
| Serialization and validation | `projectRunEvent` validates and preserves the new event's fields. | Projection exists, but no upstream event pipeline is present. |
| Public export | `RunEvent` includes the new event and its payload type. | Export exists in `run-event.ts`. |
| Existing event compatibility | Gate, pull-request, and work-started behavior remains unchanged. | Existing projection behavior is present. |

No hidden tests or patches have been authored for this blocked candidate.
