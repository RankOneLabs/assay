# List the code operations at GET /api/operations

The definition view needs to show the code operations a workflow may name, with what
each one takes, produces and can fail with. Expose them on the control plane at
`GET /api/operations`, behind the operator credential like every other `/api` read.

The response is JSON with status 200:

```json
{ "operations": [ { "key": "...", "input_schema": ..., "output_schema": ..., "error_codes": ["..."] } ] }
```

- `operations` has one entry per code operation in the operation registry
  (`src/operations/registry.ts`), in the registry's order.
- Each entry has exactly these four fields, with the registry's values: `key`,
  `input_schema`, `output_schema` and `error_codes`.
- `error_codes` is always present. An operation with no error codes lists `[]`.

The route is an operator route. When the control plane requires a token, a request
without a valid control credential is refused with 401 and code `unauthorized`, as other
operator reads are. When it is loopback-open, a loopback request is served. The route
needs no database and no core call.

Existing routes and their behavior must stay the same.

The public checks are `bun test ./tests/visible` and
`tsc --noEmit -p tsconfig.json`. The evaluator also runs private feature and
regression checks. Keep the implementation within the existing source tree. You
may add tests of your own under `tests/agent/`; they are not graded.
