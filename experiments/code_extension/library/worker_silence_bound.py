"""Task 1: let a launch set one worker's silence bound (oakridge-dbos, at `1495ec34`).

Source moves from `oakridge-dbos/src/` to `src/`, its selected tests to `tests/visible/`,
and monorepo neighbours keep their own paths (`kbbl/...`, `canonical-json/...`,
`workflow-core/fixtures/...`), so a test's `../../` still reaches the same neighbour.
"""
# ruff: noqa: E501 - embedded TypeScript keeps the fixture's own line lengths.

from __future__ import annotations

from code_extension.library import HIDDEN_MOVE, RELOCATION, Edit, LibraryTask, Patches, Requirements
from code_extension.slice import Replacement, SliceSpec

_DBOS = "oakridge-dbos/"
_KBBL_WIRE = "../../../kbbl/core/acp/resumable-wire"

_SILENCE_SOURCES = (
    "adapters/kbbl.ts",
    "core-client/client.ts",
    "core-client/core-types.ts",
    "core-client/source-types.ts",
    "domain/effect-instruction.ts",
    "domain/primitives.ts",
    "domain/projects.ts",
    "domain/prompt-template.ts",
    "domain/run-config.ts",
    "domain/unit-status.ts",
    "effects/agent-provider.ts",
    "effects/outcomes.ts",
    "effects/provider-catalog.ts",
    "effects/provider.ts",
    "effects/session-prompt.ts",
    "http/browser-write-policy.ts",
    "http/control-auth.ts",
    "http/errors.ts",
    "http/ingress.ts",
    "http/routes.ts",
    "operations/registry.ts",
    "projections/operator-event.ts",
    "projections/run-event.ts",
    "projections/session-hold.ts",
    "projections/unit-label.ts",
    "runtime/definition-store.ts",
    "storage/commit.ts",
    "storage/database.ts",
    "storage/db-types.ts",
    "storage/executor-store.ts",
    "storage/json-column-types.ts",
    "storage/operator-store.ts",
    "storage/read-store.ts",
    "storage/schema-records.ts",
    "storage/snapshot-store.ts",
)
_SILENCE_TESTS = {
    "run-config.test.ts": 2,
    "effect-instruction.test.ts": 5,
}
# Moved to the hidden group: it configures the provider's silence bound, which points
# straight at the edit the task should make the agent find.
_SILENCE_HIDDEN = "hidden/regression/tests/hidden/regression/kbbl-adapter.test.ts"
_SAMPLE_WORKFLOW = '''import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { Workflow } from "../../src/core-client/core-types";

// The pinned tests' authority fixture also opens a scratch Postgres database and the
// Rust core. These tests only read its sample workflows, so only that function ships.
const root = resolve(import.meta.dir, "../..");
export function sampleWorkflow(name: "review-loop" | "fan-out"): Workflow {
  return JSON.parse(readFileSync(resolve(root, "workflow-core/fixtures/bundles", `${name}.json`), "utf8")) as Workflow;
}
'''

WORKER_SILENCE_BOUND = SliceSpec(
    package_name="oakridge-dbos-worker-silence-bound",
    files={
        **{f"{_DBOS}src/{path}": f"src/{path}" for path in _SILENCE_SOURCES},
        **{f"{_DBOS}tests/{name}": f"tests/visible/{name}" for name in _SILENCE_TESTS},
        f"{_DBOS}tests/kbbl-adapter.test.ts": _SILENCE_HIDDEN,
        "kbbl/core/acp/resumable-wire.ts": "kbbl/core/acp/resumable-wire.ts",
        "kbbl/core/acp/types.ts": "kbbl/core/acp/types.ts",
        "kbbl/core/pwa/oakridge/operator-contracts.ts": "kbbl/core/pwa/oakridge/operator-contracts.ts",
        # Read as text by the hidden route-coverage test; outside the typecheck include.
        "kbbl/core/server/handlers/sessions.ts": "kbbl/core/server/handlers/sessions.ts",
        "kbbl/core/server/handlers/acp-per-sid.ts": "kbbl/core/server/handlers/acp-per-sid.ts",
        "canonical-json/src/index.ts": "canonical-json/src/index.ts",
        **{
            f"workflow-core/fixtures/bundles/{name}.json": f"workflow-core/fixtures/bundles/{name}.json"
            for name in ("review-loop", "fan-out", "development")
        },
    },
    replacements=(
        Replacement("src/adapters/kbbl.ts", _KBBL_WIRE, "../../kbbl/core/acp/resumable-wire"),
        Replacement("src/effects/agent-provider.ts", _KBBL_WIRE, "../../kbbl/core/acp/resumable-wire"),
        Replacement(
            "src/runtime/definition-store.ts", 'from "canonical-json"',
            'from "../../canonical-json/src/index"',
        ),
        *(
            Replacement(f"tests/visible/{name}", '"../src/', '"../../src/', count)
            for name, count in _SILENCE_TESTS.items()
        ),
        Replacement("tests/visible/effect-instruction.test.ts", '"./authority-fixture"', '"./sample-workflow"'),
        Replacement(_SILENCE_HIDDEN, '"../src/', '"../../../src/', 8),
        Replacement(_SILENCE_HIDDEN, '"./authority-fixture"', '"../../visible/sample-workflow"'),
        Replacement(
            _SILENCE_HIDDEN, '"../../kbbl/core/server/handlers"', '"../../../kbbl/core/server/handlers"',
        ),
    ),
    authored={"tests/visible/sample-workflow.ts": _SAMPLE_WORKFLOW},
    typecheck_include=(
        "src/**/*.ts", "tests/**/*.ts", "kbbl/core/acp/**/*.ts", "kbbl/core/pwa/**/*.ts",
        "canonical-json/**/*.ts",
    ),
)

_SETTINGS_TYPE: Edit = (
    "src/domain/run-config.ts",
    "export interface SessionSettings { readonly harness: string; readonly model: string; readonly effort: string | null }",
    "export interface SessionSettings {\n  readonly harness: string; readonly model: string; readonly effort: string | null;\n"
    "  /** How long this worker's session may stay silent; absent means the provider's bound. */\n"
    "  readonly max_silent_ms?: number;\n}",
)
_PARSE_OLD = (
    "const parseSessionSettings = (value: unknown): SessionSettings | null =>\n"
    "  isFields(value) && isText(value.harness) && isText(value.model) && (value.effort === null || value.effort === undefined || isText(value.effort))\n"
    "    ? { harness: value.harness, model: value.model, effort: value.effort ?? null } : null;"
)
_SETTINGS_PARSE: Edit = (
    "src/domain/run-config.ts",
    _PARSE_OLD,
    'const isBound = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value > 0;\n\n'
    "const parseSessionSettings = (value: unknown): SessionSettings | null =>\n"
    "  isFields(value) && isText(value.harness) && isText(value.model) && (value.effort === null || value.effort === undefined || isText(value.effort))\n"
    "    && (value.max_silent_ms === undefined || isBound(value.max_silent_ms))\n"
    "    ? { harness: value.harness, model: value.model, effort: value.effort ?? null,\n"
    "      ...(value.max_silent_ms === undefined ? {} : { max_silent_ms: value.max_silent_ms }) } : null;",
)
_DECODE: Edit = (
    "src/domain/effect-instruction.ts",
    "&& isString(settings.model) && isNullableString(settings.effort))",
    "&& isString(settings.model) && isNullableString(settings.effort)\n"
    "      && (settings.max_silent_ms === undefined || isCount(settings.max_silent_ms) && settings.max_silent_ms > 0))",
)


def _provider(scale: str = "") -> tuple[Edit, ...]:
    return (
        ("src/effects/agent-provider.ts",
         "  const now = config.now ?? Date.now;\n",
         "  const now = config.now ?? Date.now;\n"
         "  /** A worker's own launch bound wins over the provider's. */\n"
         "  const silenceBound = (instruction: EffectInstruction): number =>\n"
         '    instruction.worker.kind === "agent" && instruction.worker.settings?.max_silent_ms !== undefined\n'
         f"      ? instruction.worker.settings.max_silent_ms{scale} : max_silent_ms;\n"),
        ("src/effects/agent-provider.ts",
         "async function silence(kbbl: KbblClient, sid: string, signal: AbortSignal | undefined)",
         "async function silence(kbbl: KbblClient, sid: string, signal: AbortSignal | undefined, bound: number)"),
        ("src/effects/agent-provider.ts",
         "silent_for > max_silent_ms) return",
         "silent_for > bound) return"),
        ("src/effects/agent-provider.ts",
         "(limit ${Math.round(max_silent_ms / 1000)}s)",
         "(limit ${Math.round(bound / 1000)}s)"),
        ("src/effects/agent-provider.ts",
         "return silence(kbbl, handle.session_id, options.signal);",
         "return silence(kbbl, handle.session_id, options.signal, silenceBound(instruction));"),
    )


_SILENCE_PATCHES: Patches = {
    "reference.patch": (
        "Parse, carry and apply the worker's silence bound.",
        (_SETTINGS_TYPE, _SETTINGS_PARSE, _DECODE, *_provider()),
    ),
    "unreachable-provider.patch": (
        "The bound is parsed, typed and decoded, but the provider still applies only its own bound.",
        (_SETTINGS_TYPE, _SETTINGS_PARSE, _DECODE),
    ),
    "unreachable-parser.patch": (
        "The provider applies the bound, but the launch parser rebuilds settings without it, so it never arrives.",
        (_SETTINGS_TYPE, _DECODE, *_provider()),
    ),
    "wrong-units.patch": (
        "The bound reaches the provider but is read as seconds.",
        (_SETTINGS_TYPE, _SETTINGS_PARSE, _DECODE, *_provider(" * 1000")),
    ),
}

_SILENCE_REQUIREMENTS: Requirements = (
    ("A worker's launch settings may include max_silent_ms, a positive integer number of "
     "milliseconds, which the agent provider uses instead of its own bound for that worker.",
     ("bound-reaches-provider", "bound-survives-decode", "bound-lowers", "bound-units",
      "bound-overrides-provider-config")),
    ("A worker without max_silent_ms keeps the provider's bound, even when another worker in its "
     "stage sets one.", ("unset-keeps-provider-bound", "fallback-has-no-bound")),
    ("A max_silent_ms that is not a positive integer makes the configuration malformed; harness "
     "and model stay required.", ("parser-keeps-bound", "malformed-bound", "runtime-required")),
    ("An unset max_silent_ms adds no key to parsed configurations or effect instructions.",
     ("unset-adds-no-key",)),
)


TASKS = (
    LibraryTask(
        scenario="worker-silence-bound",
        slice=WORKER_SILENCE_BOUND,
        patches=_SILENCE_PATCHES,
        requirements=_SILENCE_REQUIREMENTS,
        feature_tokens=("max_silent_ms",),
        local_adaptations=(
            RELOCATION,
            "Test helpers that would open Postgres or the Rust core are replaced by the one "
            "function the shipped tests use.",
            HIDDEN_MOVE,
        ),
    ),
)
