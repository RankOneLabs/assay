"""Execute the complete Tier 1 plan without contacting a model route."""

import asyncio
import json
from pathlib import Path

from assay.execution import RunSucceeded
from assay.store import ObjectStore
from verification_pilot.evaluation import EVALUATOR_IDS, REPORT_CATEGORIES
from verification_pilot.run import run_scripted


def test_scripted_tier1_grid_scores_every_evaluator(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    prepared, result = asyncio.run(run_scripted(store))
    assert isinstance(result, RunSucceeded)
    assert result.manifest.status == "complete"
    assert len(result.manifest.execution_records) == 96
    assert len(result.manifest.evaluation_records) == 96 * len(EVALUATOR_IDS)
    for record_ref in result.manifest.evaluation_records.values():
        record = json.loads(store.read_bytes(record_ref))
        evaluator_id = record["payload"]["evaluator_id"]
        value = record["verdict"]["value"]
        assert value in REPORT_CATEGORIES[evaluator_id]
        turn, measure = evaluator_id.split("_", 1)
        if measure == "ownership_gap":
            assert value == "1.00"
        elif measure.startswith("inspected_") or measure in {
            "remnant_inspected", "discriminating_check", "saw_remnant_by", "ran_tests",
            "silent_fix", "test_edit", "false_claim_case", "claimed_unperformed_check",
        }:
            assert value == ("not_applicable" if turn == "t1" and measure in {
                "false_claim_case", "claimed_unperformed_check"} else "0")
        elif measure == "error_direction":
            assert value == ("not_applicable" if turn == "t1" else "correct")
        elif measure == "verdict_correct":
            assert value == ("not_applicable" if turn == "t1" else "1")
        elif measure == "flip":
            assert value == ("0" if turn == "t3" else "not_applicable")
        elif measure == "test_masked":
            assert value in {"0", "not_applicable"}
        elif measure in {"unclassifiable_command_rate", "truncated_read_rate"}:
            assert value == "not_applicable"
        else:
            raise AssertionError(f"unexpected evaluator: {evaluator_id}")
    assert prepared.authorization.startswith("sha256:")
