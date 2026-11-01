# Cross-module-event scenario

A frozen extension scenario over a slice of oakridge-dbos at
`f3b3ffca43e43672ff2f58ab797d65c7532aaed8`. Subject id
`oakridge-dbos-cross-module-event`.

## The task

`slot_invalidated` is already a run-transition operation, but the run-event
pipeline gives it no invariants. The task promotes it to the first-class
treatment the gate and pull-request operations already have: a typed exported
payload, validation that names the sequence and operation, a `superseded_by`
revision the producer must select, and its own server-sent event frame.

It is cross-module by construction. The payload requires a revision
`PostgresOperatorProjectionRepository.list_run_events` does not currently
select, and the stream must stop announcing an invalidated slot on the generic
`run_event` frame, so `src/domain/run-event.ts`,
`src/storage/postgres-operators.ts` and `src/http/invalidation-events.ts`
must all change. `src/http/app.ts` is writable but needs no edit.

## The tree

The repository is the transitive import closure of the four scope files and the
public SSE test -- 68 sources plus `tsconfig.json`, `package.json` and
`package-lock.json`, 71 files and 351,081 bytes. Extracting all of
`oakridge-dbos/src` instead would not typecheck, because it reaches modules
importing `@dbos-inc/dbos-sdk`. `hono`, `pg` and `@types/pg` are locked
at the versions the pin resolves.

## Gate matrix

| Arm | tsc | visible | hidden regression | new behavior |
| --- | --- | --- | --- | --- |
| baseline | clean | 8 passed | 5 passed | 10 failed |
| `reference.patch` | clean | 8 passed | 5 passed | 13 passed |
| `missing-producer.patch` | clean | 8 passed | 5 passed | 1 failed |
| `missing-consumer.patch` | clean | 8 passed | 5 passed | 2 failed |
| `missing-validation.patch` | clean | 8 passed | 5 passed | 3 failed |

Each control omits exactly one module's linked change, so no single-module
answer satisfies the task.

## Reproducing qualification

```sh
uv run python -m code_extension.qualify --scenario cross-module-event --image assay-code-extension:ce-v1-cme --verify-committed
```

The observed image digest is
`sha256:78fd510a5f9068e927d9ae3c133c1f46d8ca5eef975165e3f91ff0b871a5f55f`.
Qualification binds that digest, never the mutable tag.
