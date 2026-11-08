"""Control C1 (survey D4): let a launch set one worker's provider deadline and start budget.

The local control matched to worker-silence-bound: the same slice, so the two start trees
differ only in their package name, and the two tasks differ only in task text and hidden
tests. Both edits sit in `src/domain/`: the launch parser in `run-config.ts`, and the
instruction builder in `effect-instruction.ts`, which uses the `DEFAULT_*` constants today.
The decoder and every consumer of the instruction already read its two fields.

`kbbl-adapter.test.ts` stays in the hidden regression group, as in worker-silence-bound.
It does not reveal this task's edit, but moving it into the visible tests would make the
start tree differ from its pair's, which is the one thing a matched control must not do.
"""
# ruff: noqa: E501 - embedded TypeScript keeps the fixture's own line lengths.

from __future__ import annotations

import dataclasses

from code_extension.library import RELOCATION, Edit, LibraryTask, Patches, Requirements
from code_extension.library.worker_silence_bound import WORKER_SILENCE_BOUND

WORKER_START_BUDGET = dataclasses.replace(
    WORKER_SILENCE_BOUND, package_name="oakridge-dbos-worker-start-budget",
)

_SETTINGS_TYPE: Edit = (
    "src/domain/run-config.ts",
    "export interface SessionSettings { readonly harness: string; readonly model: string; readonly effort: string | null }",
    "export interface SessionSettings {\n  readonly harness: string; readonly model: string; readonly effort: string | null;\n"
    "  /** This worker's wall-clock budget for one provider call; absent means the default. */\n"
    "  readonly deadline_ms?: number;\n"
    "  /** How many provider starts this worker's instruction may claim; absent means the default. */\n"
    "  readonly max_start_attempts?: number;\n}",
)
_SETTINGS_PARSE: Edit = (
    "src/domain/run-config.ts",
    "const parseSessionSettings = (value: unknown): SessionSettings | null =>\n"
    "  isFields(value) && isText(value.harness) && isText(value.model) && (value.effort === null || value.effort === undefined || isText(value.effort))\n"
    "    ? { harness: value.harness, model: value.model, effort: value.effort ?? null } : null;",
    'const isBudget = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value > 0;\n\n'
    "const parseSessionSettings = (value: unknown): SessionSettings | null =>\n"
    "  isFields(value) && isText(value.harness) && isText(value.model) && (value.effort === null || value.effort === undefined || isText(value.effort))\n"
    "    && (value.deadline_ms === undefined || isBudget(value.deadline_ms))\n"
    "    && (value.max_start_attempts === undefined || isBudget(value.max_start_attempts))\n"
    "    ? { harness: value.harness, model: value.model, effort: value.effort ?? null,\n"
    "      ...(value.deadline_ms === undefined ? {} : { deadline_ms: value.deadline_ms }),\n"
    "      ...(value.max_start_attempts === undefined ? {} : { max_start_attempts: value.max_start_attempts }) } : null;",
)
_CONSTANTS = "    deadline_ms: DEFAULT_PROVIDER_DEADLINE_MS, max_start_attempts: DEFAULT_MAX_START_ATTEMPTS } };"
_RETURN = "  return { ok: true, value: { version: 1, run_id: source.run_id, action, attempt: { action_id: resolved.action_id as ActionId, seq: source.seq }, worker,\n"
_BUDGETED = (
    "    deadline_ms: budget?.deadline_ms ?? DEFAULT_PROVIDER_DEADLINE_MS,\n"
    "    max_start_attempts: budget?.max_start_attempts ?? DEFAULT_MAX_START_ATTEMPTS } };"
)
_OWN_BUDGET: Edit = (
    "src/domain/effect-instruction.ts",
    _RETURN,
    "  /** An agent worker's own launch budget wins over the defaults. */\n"
    '  const budget = worker.kind === "agent" ? worker.settings : null;\n' + _RETURN,
)
_STAGE_BUDGET: Edit = (
    "src/domain/effect-instruction.ts",
    _RETURN,
    "  /** The stage's launch budget wins over the defaults. */\n"
    "  const budget = Object.values(source.config?.sessions[source.stage] ?? {})\n"
    "    .find((settings) => settings.deadline_ms !== undefined || settings.max_start_attempts !== undefined) ?? null;\n" + _RETURN,
)
_USE_BUDGET: Edit = ("src/domain/effect-instruction.ts", _CONSTANTS, _BUDGETED)

_BUDGET_PATCHES: Patches = {
    "reference.patch": (
        "Parse the worker's deadline and start budget, and build its instruction with them.",
        (_SETTINGS_TYPE, _SETTINGS_PARSE, _OWN_BUDGET, _USE_BUDGET),
    ),
    "unreachable-constants.patch": (
        "The budget is parsed and typed, but the instruction builder still uses the default constants.",
        (_SETTINGS_TYPE, _SETTINGS_PARSE),
    ),
    "unreachable-parser.patch": (
        "The instruction builder reads the budget, but the launch parser rebuilds settings without it, so it never arrives.",
        (_SETTINGS_TYPE, _OWN_BUDGET, _USE_BUDGET),
    ),
    "wrong-stage-wide.patch": (
        "The budget reaches the instruction, but one worker's budget applies to every agent worker in its stage.",
        (_SETTINGS_TYPE, _SETTINGS_PARSE, _STAGE_BUDGET, _USE_BUDGET),
    ),
}

_BUDGET_REQUIREMENTS: Requirements = (
    ("A worker's launch settings may include deadline_ms, a positive integer number of "
     "milliseconds, and max_start_attempts, a positive integer; the effect instruction built "
     "for that agent worker carries them instead of the defaults.",
     ("deadline-reaches-instruction", "attempts-reach-instruction", "budget-survives-decode",
      "budget-lowers")),
    ("A budget field that is not set keeps its default, and a worker without a budget keeps "
     "both defaults, even when another worker in its stage sets one.",
     ("one-field-keeps-other-default", "unset-keeps-defaults", "fallback-has-no-budget")),
    ("A deadline_ms or max_start_attempts that is not a positive integer makes the "
     "configuration malformed; harness and model stay required.",
     ("parser-keeps-budget", "malformed-budget", "runtime-required")),
    ("An unset budget adds no key to parsed configurations or to the instruction's worker "
     "settings.",
     ("unset-adds-no-key",)),
)


TASKS = (
    LibraryTask(
        scenario="worker-start-budget",
        slice=WORKER_START_BUDGET,
        patches=_BUDGET_PATCHES,
        requirements=_BUDGET_REQUIREMENTS,
        feature_tokens=("deadline_ms", "max_start_attempts"),
        local_adaptations=(
            RELOCATION,
            "Test helpers that would open Postgres or the Rust core are replaced by the one "
            "function the shipped tests use.",
            "The slice is worker-silence-bound's, unchanged but for the package name, so this "
            "control's start tree matches that task's; its provider test stays in the hidden "
            "regression group there and here.",
        ),
    ),
)
