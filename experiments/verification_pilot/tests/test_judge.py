"""Fixed judge inputs and deterministic audit accounting."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast

import pytest
from jig.core.types import LLMResponse, ToolCall, Usage

from assay.adapters.consistency import CompletionNotSent
from assay.execution import EvaluationFailed, EvaluationSuccess, WorkerFailure
from assay.models import EvaluationCoordinate
from assay.store import ObjectStore
from verification_pilot.evaluation import SealedPilotTrace
from verification_pilot.judge import (
    HAND_AUDIT_FRACTION,
    JUDGE_CATEGORIES,
    JUDGE_REPEAT_COUNT,
    JUDGE_ROUTE,
    JUDGE_RUBRIC,
    PilotJudge,
    audit_agreement,
    audit_sample,
    judge_prompt,
)
from verification_pilot.tests.test_evaluation import _sealed


class FakeClient:
    def __init__(self) -> None:
        self.params: list[Any] = []
        self.closed = False

    async def complete_result(self, params: Any) -> LLMResponse | WorkerFailure:
        self.params.append(params)
        return LLMResponse("", [ToolCall("judge", "submit_output",
                                         {"source": '{"label":1}'})],
                           Usage(1, 1, 0), 1, JUDGE_ROUTE.model)

    async def aclose(self) -> None:
        self.closed = True


class FakeFactory:
    def __init__(self) -> None:
        self.client = FakeClient()

    def configuration(self) -> dict[str, Any]:
        return {"model": JUDGE_ROUTE.model, "provider": JUDGE_ROUTE.provider}

    def create(self) -> FakeClient:
        return self.client


def test_judge_prompt_excludes_arm_and_truth_and_uses_governed_route(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    trajectory = {"turns": [
        {"turn": "T1", "submission": {"title": "Verified migration", "body": "Done"},
         "tool_calls": []},
        {"turn": "T2", "submission": {"verdict": "complete", "checks_performed": "bun test"},
         "tool_calls": [{"name": "run_command", "arguments": {"command": "bun test"},
                         "exit_code": 0}]},
    ]}
    output = _sealed(store, trajectory)
    trace = SealedPilotTrace.from_output(store, output)
    for item in ("t1_claim", "cites_tests"):
        prompt = judge_prompt(item, trace)
        assert "pilot:arm:w0" not in prompt
        assert "ground_truth" not in prompt
        assert "remnants" not in prompt
        assert "ownership_group" not in prompt
        assert json.loads(prompt)["rubric"] == JUDGE_RUBRIC
    factory = FakeFactory()
    judge = PilotJudge(store, cast(Any, factory))
    assert judge.configuration()["repeats"] == JUDGE_REPEAT_COUNT == 3
    assert judge.configuration()["hand_audit_fraction"] == HAND_AUDIT_FRACTION == 0.2
    assert JUDGE_ROUTE.provider == "amazon-bedrock"
    for item in ("t1_claim", "cites_tests"):
        result = asyncio.run(judge.evaluate(
            input_value={}, output=output,
            coordinate=EvaluationCoordinate(cell_id="pilot:arm:w0", evaluator_id=item,
                                            evaluator_repeat=0)))
        assert isinstance(result, EvaluationSuccess)
        assert result.verdict == "1"
        assert result.verdict in JUDGE_CATEGORIES
        assert result.accounting.usage == {"llm_calls": 1, "input_tokens": 1,
                                           "output_tokens": 1}
        assert result.accounting.amount == 0
        assert result.accounting.coverage == "measured"
    assert factory.client.closed
    assert len(factory.client.params) == 2
    for params in factory.client.params:
        assert params.max_tokens == 256
        assert params.temperature == 0
        assert "ground_truth" not in params.messages[0].content


def test_judge_retains_accounting_on_invalid_response_and_sent_failure(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    output = _sealed(store, {"turns": [
        {"turn": "T1", "submission": {"title": "Review"}, "tool_calls": []},
    ]})
    coordinate = EvaluationCoordinate(cell_id="pilot:arm:w0", evaluator_id="t1_claim",
                                      evaluator_repeat=0)

    class ScriptedClient(FakeClient):
        def __init__(self, result: LLMResponse | WorkerFailure) -> None:
            super().__init__()
            self.result = result

        async def complete_result(self, params: Any) -> LLMResponse | WorkerFailure:
            return self.result

    for response, expected_coverage in (
        (LLMResponse("", [ToolCall("judge", "submit_output",
                                     {"source": '{"label":2}'})],
                     Usage(3, 4, 0.25), 1, JUDGE_ROUTE.model), "measured"),
        (WorkerFailure("Transport", "failed"), "uncertain"),
        (CompletionNotSent("InvalidRequest", "not sent"), "unavailable"),
    ):
        factory = FakeFactory()
        factory.client = ScriptedClient(response)
        result = asyncio.run(PilotJudge(store, cast(Any, factory)).evaluate(
            input_value={}, output=output, coordinate=coordinate))
        assert isinstance(result, EvaluationFailed)
        assert result.accounting.coverage == expected_coverage
        if isinstance(response, LLMResponse):
            assert result.accounting.usage == {"llm_calls": 1, "input_tokens": 3,
                                               "output_tokens": 4}
            assert result.accounting.amount == 0.25
        assert factory.client.closed


@pytest.mark.parametrize("submitted", ["5", '"x"', '[{"label": 1}]'])
def test_non_object_json_is_parse_failure_with_measured_cost(
    tmp_path: Path, submitted: str,
) -> None:
    store = ObjectStore(tmp_path)
    output = _sealed(store, {"turns": [
        {"turn": "T1", "submission": {"title": "Review"}, "tool_calls": []},
    ]})

    class NonObjectClient(FakeClient):
        async def complete_result(self, params: Any) -> LLMResponse | WorkerFailure:
            return LLMResponse("", [ToolCall("judge", "submit_output", {"source": submitted})],
                               Usage(3, 4, 0.25), 1, JUDGE_ROUTE.model)

    factory = FakeFactory()
    factory.client = NonObjectClient()
    result = asyncio.run(PilotJudge(store, cast(Any, factory)).evaluate(
        input_value={}, output=output,
        coordinate=EvaluationCoordinate(cell_id="pilot:arm:w0", evaluator_id="t1_claim",
                                        evaluator_repeat=0)))
    assert isinstance(result, EvaluationFailed)
    assert result.error_type == "JudgeInputOrResponse"
    assert result.accounting.usage == {"llm_calls": 1, "input_tokens": 3, "output_tokens": 4}
    assert result.accounting.amount == 0.25
    assert result.accounting.coverage == "measured"
    assert factory.client.closed


def test_seeded_twenty_percent_hand_audit_reports_agreement() -> None:
    judged = {f"cell-{i}": str(i % 2) for i in range(10)}
    sample = audit_sample(tuple(judged), "pilot-seed")
    assert len(sample) == 2
    assert sample == audit_sample(tuple(reversed(tuple(judged))), "pilot-seed")
    gold = {key: judged[key] for key in sample}
    gold[sample[0]] = str(1 - int(gold[sample[0]]))
    report = audit_agreement(judged, gold, seed="pilot-seed")
    assert report == {"sample": sample, "audited": 2, "agreed": 1,
                      "agreement": 0.5, "audit_fraction": 0.2}


def test_judge_report_configs_declare_not_applicable() -> None:
    from assay.models import StatisticalProfile
    from verification_pilot.judge import JUDGE_ITEMS, report_config_for

    ref = "sha256:" + "0" * 64
    for item in JUDGE_ITEMS:
        config = report_config_for(
            item, manifest_refs=(ref,), record_refs=(), reference_arm="reference",
            candidates=("candidate",), metric="classification",
            evaluator_repeat_aggregation="majority", worker_repeat_aggregation="majority",
            positive_label="1", statistical_profile=StatisticalProfile(seed=1,
                                                                         bootstrap_samples=100),
            engine_version="section-10-v1",
        )
        assert config.categories == JUDGE_CATEGORIES
