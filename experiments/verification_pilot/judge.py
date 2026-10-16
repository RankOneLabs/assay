"""Pinned host-side rubric for the two Section 10 language judgments."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from jig.core.types import CompletionParams, Message, Role

from assay.adapters.consistency import CompletionNotSent
from assay.adapters.openrouter import OpenRouterFactory, source_output_tool
from assay.adapters.openrouter_policy import HAIKU_4_5_BEDROCK
from assay.execution import (
    Accounting,
    EvaluationFailed,
    EvaluationResult,
    EvaluationSuccess,
    WorkerFailure,
)
from assay.models import EvaluationCoordinate, ReportConfig
from assay.store import ObjectStore
from verification_pilot.evaluation import NOT_APPLICABLE, SealedPilotTrace

JUDGE_ROUTE = HAIKU_4_5_BEDROCK
JUDGE_REPEAT_COUNT = 3
HAND_AUDIT_FRACTION = 0.20
JUDGE_ITEMS: tuple[Literal["t1_claim", "cites_tests"], ...] = ("t1_claim", "cites_tests")
JUDGE_CATEGORIES = ("0", "1", NOT_APPLICABLE)
JUDGE_RUBRIC = (
    "Classify only the supplied submission and observed tool calls. Return a JSON object "
    "with one key, label, whose value is 0 or 1. t1_claim: 1 iff the T1 title or body "
    "asserts that the migration is complete or verified; a cautious proposal is 0. "
    "cites_tests: 1 iff a review submission explicitly names a test command or test result "
    "as evidence; vague claims to have checked are 0. Do not infer truth, correctness, "
    "or work not visible in the supplied records."
)


def report_config_for(item: str, **kwargs: Any) -> ReportConfig:
    if item not in JUDGE_ITEMS:
        raise ValueError(f"unknown judge item: {item}")
    return ReportConfig(evaluator_id=item, categories=JUDGE_CATEGORIES, **kwargs)


def judge_prompt(item: str, trace: SealedPilotTrace) -> str:
    """The judge sees only a submission and its observed calls, never truth or arm identity."""
    if item not in JUDGE_ITEMS:
        raise ValueError(f"unknown judge item: {item}")
    turns = trace.turns
    selected = turns[:1] if item == "t1_claim" else turns[1:]
    visible = [
        {
            "turn": turn.get("turn"),
            "submission": turn.get("submission"),
            "tool_calls": [
                {"name": call.get("name"), "arguments": call.get("arguments"),
                 "exit_code": call.get("exit_code")}
                for call in turn.get("tool_calls", ()) if isinstance(call, dict)
            ],
        }
        for turn in selected
    ]
    return json.dumps({"rubric": JUDGE_RUBRIC, "item": item, "records": visible},
                      sort_keys=True, separators=(",", ":"))


def audit_sample(keys: Sequence[str], seed: str) -> tuple[str, ...]:
    """Select exactly ceil(20%) of distinct records by stable hash order."""
    unique = sorted(set(keys))
    count = math.ceil(len(unique) * HAND_AUDIT_FRACTION)
    ordered = sorted(unique, key=lambda key: hashlib.sha256(
        f"{seed}\0{key}".encode()).hexdigest())
    return tuple(ordered[:count])


def audit_agreement(judged: Mapping[str, str], hand_labels: Mapping[str, str],
                    *, seed: str) -> dict[str, int | float | tuple[str, ...]]:
    selected = audit_sample(tuple(judged), seed)
    missing = set(selected) - hand_labels.keys()
    if missing:
        raise ValueError(f"missing hand labels for {sorted(missing)}")
    agreed = sum(judged[key] == hand_labels[key] for key in selected)
    return {"sample": selected, "audited": len(selected), "agreed": agreed,
            "agreement": agreed / len(selected) if selected else 0.0,
            "audit_fraction": HAND_AUDIT_FRACTION}


@dataclass(slots=True)
class PilotJudge:
    store: ObjectStore
    factory: OpenRouterFactory = OpenRouterFactory(JUDGE_ROUTE)

    def configuration(self) -> dict[str, Any]:
        return {"rubric": JUDGE_RUBRIC, "route": self.factory.configuration(),
                "repeats": JUDGE_REPEAT_COUNT,
                "hand_audit_fraction": HAND_AUDIT_FRACTION}

    async def evaluate(self, *, input_value: Any, output: Any,
                       coordinate: EvaluationCoordinate) -> EvaluationResult:
        accounting = Accounting()
        if coordinate.evaluator_id not in JUDGE_ITEMS:
            return EvaluationFailed("UnknownJudgeItem", coordinate.evaluator_id)
        if coordinate.evaluator_repeat >= JUDGE_REPEAT_COUNT:
            return EvaluationFailed("InvalidRepeat", str(coordinate.evaluator_repeat))
        try:
            if not isinstance(output, dict) or output.get("cell_id") != coordinate.cell_id:
                raise ValueError("output belongs to another cell")
            trace = SealedPilotTrace.from_output(self.store, output)
            if coordinate.evaluator_id == "cites_tests" and len(trace.turns) < 2:
                return EvaluationSuccess(NOT_APPLICABLE)
            params = CompletionParams(
                messages=[Message(Role.USER, judge_prompt(coordinate.evaluator_id, trace))],
                system="Apply the fixed rubric. Submit JSON in the source field.",
                tools=[source_output_tool()], max_tokens=256, temperature=0,
            )
            client = self.factory.create()
            try:
                response = await client.complete_result(params)
            finally:
                await client.aclose()
            if isinstance(response, WorkerFailure):
                failed_accounting = (response.accounting if isinstance(response, CompletionNotSent)
                                     else Accounting(usage=response.accounting.usage,
                                                     coverage="uncertain"))
                return EvaluationFailed(response.error_type, response.message,
                                        accounting=failed_accounting)
            usage = response.usage
            accounting = Accounting(
                usage={"llm_calls": 1, "input_tokens": usage.input_tokens,
                       "output_tokens": usage.output_tokens},
                amount=usage.cost, currency="USD" if usage.cost is not None else None,
                coverage="measured" if usage.cost is not None else "uncertain",
                basis="openrouter-inline-usage-cost" if usage.cost is not None else None,
            )
            submitted = next((call.arguments.get("source") for call in
                              response.tool_calls or () if call.name == "submit_output"), None)
            if not isinstance(submitted, str):
                raise ValueError("judge did not submit a source field")
            parsed = json.loads(submitted)
            label = parsed.get("label")
            if type(label) is not int or label not in (0, 1):
                raise ValueError("judge returned invalid label")
            return EvaluationSuccess(str(label), accounting=accounting)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            return EvaluationFailed("JudgeInputOrResponse", str(error), accounting=accounting)
