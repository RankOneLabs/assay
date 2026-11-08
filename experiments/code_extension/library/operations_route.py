"""Task D2: an operator route listing the code operations (oakridge-dbos, at `1495ec34`).

Source moves from `oakridge-dbos/src/` to `src/`, its selected tests to `tests/visible/`,
and `canonical-json` keeps its own path. The route table's own test moves to the hidden
regression group, less the one assertion that every registered route is classified: that
assertion moves, with the new route in it, into the hidden new-behavior group, so a
handler registered without its table entry fails as unreachable rather than as a
regression.
"""
# ruff: noqa: E501 - embedded TypeScript keeps the fixture's own line lengths.

from __future__ import annotations

from code_extension.library import HIDDEN_MOVE, RELOCATION, Edit, LibraryTask, Patches, Requirements
from code_extension.slice import Replacement, SliceSpec

_DBOS = "oakridge-dbos/"

_ROUTE_SOURCES = (
    "core-client/client.ts",
    "core-client/core-types.ts",
    "core-client/source-types.ts",
    "domain/delegated-session.ts",
    "domain/effect-instruction.ts",
    "domain/primitives.ts",
    "domain/projects.ts",
    "domain/prompt-template.ts",
    "domain/pull-request.ts",
    "domain/repository-provisioning.ts",
    "domain/run-config.ts",
    "domain/unit-status.ts",
    "effects/provider-catalog.ts",
    "http/app.ts",
    "http/browser-write-policy.ts",
    "http/change-key.ts",
    "http/collaboration.ts",
    "http/control-auth.ts",
    "http/errors.ts",
    "http/events.ts",
    "http/ingress.ts",
    "http/merge-status.ts",
    "http/operator-api.ts",
    "http/projects.ts",
    "http/read-models.ts",
    "http/routes.ts",
    "operations/outcome.ts",
    "operations/pull-request-observe.ts",
    "operations/registry.ts",
    "operations/repository-prepare.ts",
    "operations/runner.ts",
    "projections/artifact-view.ts",
    "projections/attention.ts",
    "projections/collaboration-view.ts",
    "projections/definition-view.ts",
    "projections/history-view.ts",
    "projections/inbox.ts",
    "projections/operator-event.ts",
    "projections/run-event.ts",
    "projections/run-view.ts",
    "projections/schema-view.ts",
    "projections/serialization-view.ts",
    "projections/session-hold.ts",
    "projections/unit-label.ts",
    "projections/unit-view.ts",
    "runtime/definition-store.ts",
    "runtime/github-pull-requests.ts",
    "runtime/project-identity.ts",
    "storage/collaboration-store.ts",
    "storage/commit.ts",
    "storage/database.ts",
    "storage/db-types.ts",
    "storage/executor-store.ts",
    "storage/json-column-types.ts",
    "storage/operator-store.ts",
    "storage/read-store.ts",
    "storage/run-deletion.ts",
    "storage/schema-records.ts",
    "storage/snapshot-store.ts",
)
# Pinned tests that need neither Postgres nor the Rust core, with their `../src/` counts.
_ROUTE_TESTS = {
    "change-key.test.ts": 2,
    "attention.test.ts": 5,
    "unit-view.test.ts": 4,
    "operator-event.test.ts": 2,
    "unit-label.test.ts": 2,
}
# Moved to the hidden group: it asserts that the registered routes equal the route table,
# which names the non-local edit, and that an unclassified route is refused.
_ROUTE_HIDDEN = "hidden/regression/tests/hidden/regression/control-auth.test.ts"
_EQUALITY_TEST = '''const registered = (app: ReturnType<typeof createHttpApp>) =>
  app.routes.filter((route) => route.method !== "ALL").map((route) => `${route.method} ${route.path}`).sort();

test("every registered route is classified in the route table, and every classified route is registered", () => {
  expect(registered(httpApp(null))).toEqual(HTTP_ROUTES.map((route) => `${route.method} ${route.path}`).sort());
});
'''
_EQUALITY_MOVED = (
    "// The assertion that every registered route is classified, and every classified route\n"
    "// registered, runs in the hidden new-behavior group, with GET /api/operations in it.\n"
)

OPERATIONS_ROUTE = SliceSpec(
    package_name="oakridge-dbos-operations-route",
    files={
        **{f"{_DBOS}src/{path}": f"src/{path}" for path in _ROUTE_SOURCES},
        **{f"{_DBOS}tests/{name}": f"tests/visible/{name}" for name in _ROUTE_TESTS},
        f"{_DBOS}tests/control-auth.test.ts": _ROUTE_HIDDEN,
        "canonical-json/src/index.ts": "canonical-json/src/index.ts",
    },
    replacements=(
        Replacement(
            "src/runtime/definition-store.ts", 'from "canonical-json"',
            'from "../../canonical-json/src/index"',
        ),
        *(
            Replacement(f"tests/visible/{name}", '"../src/', '"../../src/', count)
            for name, count in _ROUTE_TESTS.items()
        ),
        Replacement(_ROUTE_HIDDEN, '"../src/', '"../../../src/', 5),
        Replacement(_ROUTE_HIDDEN, _EQUALITY_TEST, _EQUALITY_MOVED),
    ),
    typecheck_include=("src/**/*.ts", "tests/**/*.ts", "canonical-json/**/*.ts"),
)

_TABLE: Edit = (
    "src/http/routes.ts",
    '  { method: "GET", path: "/api/prompts", authority: "operator" },\n',
    '  { method: "GET", path: "/api/prompts", authority: "operator" },\n'
    '  { method: "GET", path: "/api/operations", authority: "operator" },\n',
)
_IMPORT: Edit = (
    "src/http/app.ts",
    'import { installMergeStatus } from "./merge-status";\n',
    'import { installMergeStatus } from "./merge-status";\n'
    'import { selectOperationList } from "./operations";\n',
)
_HANDLER: Edit = (
    "src/http/app.ts",
    "  app.get(\"/api/prompts\", () => { try { return Response.json(listCommittedPrompts()); }\n",
    "  app.get(\"/api/operations\", (context) => context.json(selectOperationList()));\n"
    "  app.get(\"/api/prompts\", () => { try { return Response.json(listCommittedPrompts()); }\n",
)
_CONTRACT: Edit = (
    "src/http/operator-api.ts",
    'export type { ProjectDraft, ProjectList, ProjectView } from "./projects";\n',
    'export type { ProjectDraft, ProjectList, ProjectView } from "./projects";\n'
    'export type { OperationList, OperationView } from "./operations";\n',
)


def _view(error_codes: bool = True) -> Edit:
    field = "  readonly error_codes: readonly string[];\n" if error_codes else ""
    entry = "{ key, input_schema, output_schema, error_codes }" if error_codes else "{ key, input_schema, output_schema }"
    return (
        "src/http/operations.ts",
        "",
        'import type { TypeExpression } from "../core-client/core-types";\n'
        'import { OPERATION_REGISTRY } from "../operations/registry";\n\n'
        "/** One code operation a workflow may name, as the definition view reads it. */\n"
        "export interface OperationView {\n"
        "  readonly key: string;\n"
        "  readonly input_schema: TypeExpression;\n"
        "  readonly output_schema: TypeExpression;\n"
        f"{field}"
        "}\n"
        "export interface OperationList { readonly operations: readonly OperationView[] }\n\n"
        "/** The body of `GET /api/operations`: the registry, in its own order. */\n"
        "export const selectOperationList = (): OperationList => ({\n"
        f"  operations: OPERATION_REGISTRY.map(({entry}): OperationView => ({entry})),\n"
        "});\n",
    )


_ROUTE_PATCHES: Patches = {
    "reference.patch": (
        "List the registry at GET /api/operations, classify the route as an operator route, and export its type.",
        (_TABLE, _IMPORT, _HANDLER, _CONTRACT, _view()),
    ),
    "unreachable-unclassified.patch": (
        "The handler is registered, but the route table does not classify it, so the fail-closed middleware refuses it as unknown_route.",
        (_IMPORT, _HANDLER, _CONTRACT, _view()),
    ),
    "wrong-no-error-codes.patch": (
        "The route is classified and served, but its operations leave out their error codes.",
        (_TABLE, _IMPORT, _HANDLER, _CONTRACT, _view(error_codes=False)),
    ),
}

_ROUTE_REQUIREMENTS: Requirements = (
    ("GET /api/operations answers an operator 200, with or without a control token configured, "
     "and the route table classifies it like every other registered route.",
     ("served-with-token", "served-loopback", "route-table-complete")),
    ("The body is { operations: [...] }, one entry per registered code operation in registry "
     "order, each with its key, input_schema, output_schema and error_codes, an empty array when "
     "it has none.",
     ("lists-registry", "empty-error-codes")),
    ("GET /api/operations is an operator route: without the control credential it answers 401 "
     "unauthorized.",
     ("operator-authority", "refused-without-credential")),
)


TASKS = (
    LibraryTask(
        scenario="operations-route",
        slice=OPERATIONS_ROUTE,
        patches=_ROUTE_PATCHES,
        requirements=_ROUTE_REQUIREMENTS,
        feature_tokens=("/api/operations",),
        local_adaptations=(
            RELOCATION,
            HIDDEN_MOVE,
            "The pinned route-table test ships in the hidden regression group without its "
            "registered-equals-classified assertion; that assertion runs in the hidden "
            "new-behavior group, with the new route in it.",
        ),
    ),
)
