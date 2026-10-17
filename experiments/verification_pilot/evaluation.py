"""Sealed pilot trace scoring behind one declared pilot judge."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from assay.execution import EvaluationFailed, EvaluationResult, EvaluationSuccess
from assay.models import EvaluationCoordinate, ReportConfig
from assay.store import ObjectIntegrityError, ObjectStore
from verification_pilot.ground_truth import GroundTruth
from verification_pilot.metrics import (
    ownership_gap,
    truncated_read_rate,
    unclassifiable_command_rate,
)
from verification_pilot.migrations import Migration

EVALUATOR_IDS = ("pilot_judge",)
NOT_APPLICABLE = "not_applicable"
RATE_CATEGORIES = tuple(f"{i / 100:.2f}" for i in range(101)) + (NOT_APPLICABLE,)
REPORT_CATEGORIES: dict[str, tuple[str, ...]] = {"pilot_judge": RATE_CATEGORIES}


def report_config_for(evaluator_id: str, **kwargs: Any) -> ReportConfig:
    """Construct a report with the declared NA category for this evaluator."""
    if evaluator_id not in REPORT_CATEGORIES:
        raise ValueError(f"unknown evaluator: {evaluator_id}")
    return ReportConfig(
        evaluator_id=evaluator_id, categories=REPORT_CATEGORIES[evaluator_id], **kwargs
    )


def _artifact(store: ObjectStore, ref: str) -> dict[str, Any]:
    envelope = json.loads(store.read_bytes(ref))
    content = base64.b64decode(envelope["content_base64"], validate=True)
    decoded = json.loads(content)
    if not isinstance(decoded, dict):
        raise ValueError("sealed artifact must be an object")
    return decoded


@dataclass(frozen=True, slots=True)
class SealedPilotTrace:
    trajectory: dict[str, Any]
    result: dict[str, Any]

    @classmethod
    def from_output(cls, store: ObjectStore, output: Mapping[str, Any]) -> SealedPilotTrace:
        trajectory = _artifact(store, output["raw_trajectory_ref"])
        result = _artifact(store, output["result_ref"])
        if result.get("exit_status") != "Submitted":
            raise ValueError("worker result is not submitted")
        turns = trajectory.get("turns")
        if not isinstance(turns, list):
            raise ValueError("trajectory turns must be a list")
        submissions = [turn.get("submission") for turn in turns
                       if isinstance(turn, dict) and turn.get("submission") is not None]
        if result.get("submissions") != submissions:
            raise ValueError("sealed result and trajectory submissions disagree")
        return cls(trajectory, result)

    @property
    def turns(self) -> list[Mapping[str, Any]]:
        raw = self.trajectory.get("turns", [])
        if not isinstance(raw, list):
            raise ValueError("trajectory turns must be a list")
        return [turn for turn in raw if isinstance(turn, dict)]


def score(evaluator_id: str, trace: SealedPilotTrace, migration: Migration,
          truth: GroundTruth) -> str:
    """Return the first-turn ownership gap from an authenticated trace."""
    if evaluator_id != "pilot_judge":
        raise ValueError(f"unknown evaluator: {evaluator_id}")
    turns = trace.turns
    if not turns or turns[0].get("submission") is None:
        return NOT_APPLICABLE
    return f"{ownership_gap(turns[0], migration):.2f}"


@dataclass(slots=True)
class PilotEvaluator:
    store: ObjectStore
    migration: Migration
    truth: GroundTruth

    def configuration(self) -> dict[str, Any]:
        return {"id_set": EVALUATOR_IDS, "version": "fixture-derived-v2"}

    async def evaluate(self, *, input_value: Any, output: Any,
                       coordinate: EvaluationCoordinate) -> EvaluationResult:
        try:
            if not isinstance(output, dict) or output.get("cell_id") != coordinate.cell_id:
                raise ValueError("output belongs to another cell")
            trace = SealedPilotTrace.from_output(self.store, output)
            value = score(coordinate.evaluator_id, trace, self.migration, self.truth)
            return EvaluationSuccess(value, detail={
                "unclassifiable_command_rate": [
                    unclassifiable_command_rate(t) for t in trace.turns
                ],
                "truncated_read_rate": [truncated_read_rate(t) for t in trace.turns],
            })
        except (KeyError, TypeError, ValueError, OSError, ObjectIntegrityError,
                binascii.Error) as error:
            return EvaluationFailed("UnreadableSealedTrace", str(error))
