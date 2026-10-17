"""The one declared evaluator consumes sealed pilot traces."""

from __future__ import annotations

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
from verification_pilot.metrics import remnant_read


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
