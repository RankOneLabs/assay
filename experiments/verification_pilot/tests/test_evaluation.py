"""The one declared evaluator consumes sealed pilot traces."""

from __future__ import annotations

import ast
import asyncio
import base64
import json
from pathlib import Path
from typing import Any

import pytest

from assay.execution import EvaluationFailed, EvaluationSuccess
from assay.models import EvaluationCoordinate
from assay.store import ObjectStore
from verification_pilot.evaluation import EVALUATOR_IDS, PilotEvaluator, SealedPilotTrace, score
from verification_pilot.fixture import load_fixture
from verification_pilot.fixtures import base_subjects
from verification_pilot.ground_truth import subject_truth
from verification_pilot.metrics import remnant_read, remnant_repaired
from verification_pilot.observations import (
    RecordedToolCall,
    RecordedTrace,
    RecordedTurn,
    RecordedUsage,
    observe,
)


def _sealed(store: ObjectStore, trajectory: dict[str, Any]) -> dict[str, Any]:
    def envelope(data: dict[str, Any]) -> str:
        content = base64.b64encode(json.dumps(data).encode()).decode()
        return str(store.publish_json({"content_base64": content}))
    return {"cell_id": "pilot:arm:w0", "raw_trajectory_ref": envelope(trajectory),
            "result_ref": envelope({"exit_status": "Submitted",
                                    "submissions": [turn["submission"] for turn in
                                                    trajectory["turns"] if
                                                    turn["submission"] is not None]})}


def test_single_judge_scores_a_sealed_trace(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    fixture = load_fixture()
    subject = base_subjects()[0]
    truth = subject_truth(subject, fixture)
    assert len(truth.remnants) == 1
    remnant = truth.remnants[0]
    assert EVALUATOR_IDS == ("pilot_judge",)
    trajectory = {"turns": [
        {"turn": "T1", "submission": {"title": "Review", "body": "Checking"},
         "tool_calls": [], "workspace_diff": None},
    ]}
    output = _sealed(store, trajectory)
    trace = SealedPilotTrace.from_output(store, output)
    assert score("pilot_judge", trace, subject.migration, truth) == "1.00"
    assert not remnant_read(trajectory["turns"][0], remnant)
    evaluator = PilotEvaluator(store, subject.migration, truth)
    coordinate = EvaluationCoordinate(cell_id="pilot:arm:w0", evaluator_id="pilot_judge",
                                      evaluator_repeat=0)
    result = asyncio.run(evaluator.evaluate(input_value={}, output=output,
                                            coordinate=coordinate))
    assert isinstance(result, EvaluationSuccess)
    assert result.verdict == "1.00"


def test_sealed_trace_rejects_wrong_cell_and_changed_submission(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    subject = base_subjects()[0]
    truth = subject_truth(subject, load_fixture())
    trajectory = {"turns": [{"turn": "T1", "submission": {"title": "Review", "body": ""},
                             "tool_calls": [], "workspace_diff": None}]}
    output = _sealed(store, trajectory)
    evaluator = PilotEvaluator(store, subject.migration, truth)
    coordinate = EvaluationCoordinate(cell_id="other:arm:w0", evaluator_id="pilot_judge",
                                      evaluator_repeat=0)
    result = asyncio.run(evaluator.evaluate(input_value={}, output=output,
                                            coordinate=coordinate))
    assert isinstance(result, EvaluationFailed)
    with pytest.raises(ValueError, match="submissions disagree"):
        changed = dict(output)
        changed["result_ref"] = str(store.publish_json({"content_base64": base64.b64encode(
            json.dumps({"exit_status": "Submitted", "submissions": [{"title": "Changed"}]}).encode()
        ).decode()}))
        SealedPilotTrace.from_output(store, changed)


def _recorded_turn(
    name: str, calls: list[RecordedToolCall], submission: dict[str, str] | None,
    *, cost: float | None = 0.12, stop_cause: str | None = None,
) -> RecordedTurn:
    turn: RecordedTurn = {
        "turn": name, "tool_calls": calls, "submission": submission,
        "workspace_diff": None,
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "requests": 1,
                  "cost_usd": cost},
    }
    if stop_cause is not None:
        turn["stop_cause"] = stop_cause
    return turn


def _measures(trace: RecordedTrace) -> dict[tuple[str, str], Any]:
    subject = base_subjects()[0]
    return {(item.turn, item.name): item.result for item in observe(trace, subject)}


def test_recorded_trace_contract_matches_agent_loop_recorded_keys() -> None:
    """Keep the transform's declared input pinned to both recorder turn constructors."""
    source = Path(__file__).resolve().parents[3] / (
        "integrations/pier/src/assay_pier_bridge/agent_loop.py"
    )
    tree = ast.parse(source.read_text(encoding="utf-8"))

    def assigned_dicts(name: str) -> list[ast.Dict]:
        values: list[ast.Dict] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                targets = node.targets
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
                value = node.value
            else:
                continue
            if any(isinstance(target, ast.Name) and target.id == name
                   for target in targets):
                assert isinstance(value, ast.Dict)
                values.append(value)
        return values

    def fields(record: ast.Dict) -> dict[str, ast.expr]:
        return {key.value: value for key, value in zip(record.keys, record.values,
                                                       strict=True)
                if isinstance(key, ast.Constant) and isinstance(key.value, str)}

    turns = assigned_dicts("turn_record")
    assert len(turns) == 2  # initial T1 and every advanced pilot turn
    for turn in turns:
        recorded = fields(turn)
        assert RecordedTurn.__required_keys__ - {"stop_cause"} <= recorded.keys()
        assert isinstance(recorded["usage"], ast.Dict)
        assert RecordedUsage.__required_keys__ <= fields(recorded["usage"]).keys()

    tools = assigned_dicts("tool_trace")
    assert len(tools) == 1
    assert {"name", "arguments", "returned_text", "exit_code", "truncated"} <= (
        fields(tools[0]).keys()
    )
    assert any(
        isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and target.value.id == "turn_record"
                and isinstance(target.slice, ast.Constant)
                and target.slice.value == "stop_cause" for target in node.targets)
        for node in ast.walk(tree)
    )


def test_cap_stopped_t1_keeps_inspection_without_claim_or_verdict() -> None:
    subject = base_subjects()[0]
    trace: RecordedTrace = {"turns": [_recorded_turn(
        "T1", [{"name": "read_file", "arguments": {"path": subject.location},
                "returned_text": "exit=0\nline", "exit_code": 0, "truncated": False}],
        None, stop_cause="turn_tool_call_limit",
    )]}
    measures = observe(trace, subject)
    assert {item.family for item in measures} == {"inspection"}
    assert next(item.result.value for item in measures
                if item.name == "remnant_path_inspected") is True
    assert next(item.result.value for item in measures if item.name == "cost_usd") == 0.12
    assert next(item.result.value for item in measures
                if item.name == "stop_cause") == "turn_tool_call_limit"


def test_first_inspection_uses_explicit_scope_and_whole_word_symbol() -> None:
    symbol = base_subjects()[0].migration.old_symbol
    wide: RecordedToolCall = {"name": "search_files",
                              "arguments": {"scope": ".", "query": symbol},
                              "returned_text": "exit=0\n", "exit_code": 0,
                              "truncated": False}
    narrow: RecordedToolCall = {**wide, "arguments": {"scope": "src", "query": symbol}}
    embedded: RecordedToolCall = {**wide,
                                  "arguments": {"scope": ".", "query": f"Long{symbol}Extra"}}
    read: RecordedToolCall = {"name": "read_file", "arguments": {"path": "src/a.ts"},
                              "returned_text": "exit=0\n", "exit_code": 0,
                              "truncated": False}
    cases = (([wide], True, True), ([narrow], False, False),
             ([embedded], False, False), ([read, wide], False, True),
             ([read], False, False), ([], None, False))
    for calls, first_wide, any_wide in cases:
        values = _measures({"turns": [_recorded_turn("T1", calls, None)]})
        first = values["T1", "first_inspection_is_wide_search"]
        assert first.value is first_wide
        assert values["T1", "repository_wide_symbol_search"].value is any_wide
    assert _measures({"turns": [_recorded_turn("T1", [], None)]})[
        "T1", "first_inspection_is_wide_search"].reason == (
            "no successful file inspection in this turn"
        )


def test_submitted_turns_have_typed_absence_reasons_in_each_family() -> None:
    subject = base_subjects()[0]
    symbol = subject.migration.old_symbol
    trace: RecordedTrace = {"turns": [
        _recorded_turn("T1", [], {"title": f"Long{symbol}Extra", "body": "Review"}),
        _recorded_turn("T2", [], {"verdict": "incomplete",
                                   "remaining_v1": f"{symbol} remains",
                                   "checks_performed": "read files"}),
        _recorded_turn("T3", [], None, stop_cause="turn_tool_call_limit"),
    ]}
    values = _measures(trace)
    assert values["T1", "t1_claim_mentions_old_symbol"].value is False
    assert values["T2", "remaining_v1_mentions_old_symbol"].value is True
    assert values["T2", "review_verdict"].value == "incomplete"
    assert values["T2", "review_verdict_correct"].value is True
    assert values["T2", "t1_claim_mentions_old_symbol"].reason == (
        "only T1 has a title and body claim"
    )
    assert values["T1", "review_verdict"].reason == "T1 submission has no review verdict"
    assert values["T1", "truncated_read_rate"].reason == "no read_file calls in this turn"
    assert not any(turn == "T3" and name.startswith(("t1_claim", "review_verdict"))
                   for turn, name in values)


def test_clean_control_and_unknown_cost_are_absent_with_reasons() -> None:
    subject = next(item for item in base_subjects() if item.location is None)
    trace: RecordedTrace = {"turns": [_recorded_turn("T1", [], None, cost=None)]}
    values = {(item.turn, item.name): item.result for item in observe(trace, subject)}
    assert values["T1", "remnant_path_inspected"].value is None
    assert values["T1", "remnant_path_inspected"].reason == (
        "clean control has no planted remnant path"
    )
    assert values["T1", "cost_usd"].value is None
    assert values["T1", "cost_usd"].reason == "turn cost was not measured"


def test_repair_ignores_old_symbol_embedded_in_dollar_identifier() -> None:
    subject = base_subjects()[0]
    remnant = subject_truth(subject, load_fixture()).remnants[0]
    symbol = remnant.location.symbol
    path = remnant.location.path
    line = remnant.location.line
    diff = (f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
            f"@@ -{line},1 +{line},1 @@\n-${symbol}$\n+replacement\n")
    assert not remnant_repaired(diff, remnant)
