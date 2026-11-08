# Operations route

Subject `oakridge-dbos-operations-route` adds an operator read, `GET /api/operations`,
that lists the code operations a workflow may name. It is survey item D2, at oakridge
`1495ec34`. Its shape is the code's own: a handler in `src/http/app.ts`, and a route table
in `src/http/routes.ts` that fails closed. A request whose route the table does not list
is refused as `unknown_route` (404) before it reaches any handler, even a registered one.
The type checker does not point at the table, and the task text does not name it.

## Provenance

Cut by `uv run python -m code_extension.slice --scenario operations-route --oakridge
<oakridge>` from oakridge commit `1495ec34`. The slice spec in
`code_extension/library/operations_route.py` lists every pinned file and every edit made
while moving it.

| Fixture path | Source at the pin | Why included |
| --- | --- | --- |
| `src/**` | `oakridge-dbos/src/**`, the import closure of `http/app.ts`, `http/operator-api.ts` and `operations/registry.ts` | The code the feature passes through |
| `canonical-json/src/index.ts` | same path | The workspace package the definition store imports |
| `tests/visible/{change-key,attention,unit-view,operator-event,unit-label}.test.ts` | `oakridge-dbos/tests/` | Public checks: the pinned tests in this closure that need neither Postgres nor the Rust core |
| `package.json`, `package-lock.json` | `integrations/pier/scenario_library/` | The image's dependency lock, renamed; versions match oakridge's `bun.lock` |
| `tsconfig.json` | authored | The pinned compiler options, flattened |

The repository has 68 files and 452,592 bytes, under the 200-file and 1,000,000-byte
limits. `kysely` and `pg` are imported by the storage modules but never connected.

## Edits made while moving files

- `canonical-json` is imported by relative path instead of as a workspace package.
- Tests move down one directory, so `../src/` becomes `../../src/` (visible) or
  `../../../src/` (hidden).
- The hidden copy of `control-auth.test.ts` drops one test and its helper: "every
  registered route is classified in the route table, and every classified route is
  registered". That assertion runs in the hidden new-behavior group instead, with
  `GET /api/operations` in it (see below).

No production behavior is changed.

## Hidden groups

- **Regression:** `control-auth.test.ts`, the pinned control-plane tests: bind policy,
  token checks, the fail-closed refusal of an unclassified route, and the list of
  non-operator routes. It moved out of the visible tests because it asserts that the
  registered routes equal the route table, which names the edit the task should make the
  agent find.
  - That one assertion moved again, into new behavior. Left in regression, a handler
    registered without its table entry would fail regression as well as reachability.
    The negative patch for exactly that mistake could then not qualify, because a negative
    may fail only its intended group. In new behavior it is a reachability test, and it
    fails at baseline because the new route is in neither list.
- **New behavior:** `operations-route.test.ts`, through `createHttpApp` with stub
  dependencies and `app.request()`. Titles start with `reachability:` when the test fails
  unless the route is served on the normal path, and `semantics:` otherwise.

## Patches

| Patch | What it does | Should fail |
| --- | --- | --- |
| `reference.patch` | Handler, route-table entry, and the response type exported from `operator-api.ts` | nothing |
| `unreachable-unclassified.patch` | Handler and type, but no route-table entry, so the request gets 404 `unknown_route` | reachability |
| `wrong-no-error-codes.patch` | Served and classified, but entries leave out `error_codes` | semantics only |

The survey's other wrong-semantics option, authority `"open"`, is not used. The pinned
regression test that lists the non-operator routes fails on it, so it would not fail
semantics only.
