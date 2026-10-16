"""Pilot-specific inference is checked independently of the shared report engine."""

from pathlib import Path

import pytest

from assay.execution import RunSucceeded, execute_plan
from assay.models import RuntimeProfile
from assay.report_engine import ReportError, build_report
from assay.store import ObjectStore
from verification_pilot.report import (
    Observation,
    h1_ownership_gap,
    h4_own_vs_teammate,
    model_report,
    paired_config,
)
from verification_pilot.run import GridEvaluator, ScriptedWorker, run_scripted, subject_truth
from verification_pilot.study import compile_pilot_plan, pilot_subjects


def test_h1_exact_one_sample_sign_test_against_zero() -> None:
    rows = [
        Observation("route", f"s{i}", "migration", "group_a", 0, 1,
                    "t1-native", "t1_ownership_gap", value)
        for i, value in enumerate(("0.25", "0.50", "1.00", "0.00", "0.00"))
    ]
    result = h1_ownership_gap(rows, "t1-native")
    assert result["n"] == 5
    assert result["improved"] == 3
    assert result["regressed"] == 0
    assert result["ties"] == 2
    assert result["p_value"] == 0.25  # 2 * P(Binomial(3, .5) = 0)
    assert result["test"] == "one_sample_exact_sign_against_zero"


def test_h4_is_between_subjects_within_one_arm() -> None:
    rows = [
        Observation("route", f"{migration}-{group}", migration, group, 0, 1,
                    "t1-native", "t1_remnant_inspected", value)
        for migration in ("a", "b", "c", "d")
        for group, value in (("group_a", "1"), ("group_b", "0"))
    ]
    result = h4_own_vs_teammate(rows, "t1-native", own_group="group_a")
    assert result["n"] == 4
    assert result["mean_difference"] == 1
    assert result["p_value"] is None
    assert all(pair["own"] == 1 and pair["teammate"] == 0 for pair in result["pairs"])


@pytest.mark.asyncio
async def test_scripted_grid_builds_paired_h2_and_separate_model_report(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "store")
    _, run = await run_scripted(store)
    assert isinstance(run, RunSucceeded)
    ref = str(run.manifest_ref)
    config = paired_config(store, (ref,), evaluator_id="t1_remnant_inspected",
                           reference_arm="t1-native", candidate_arm="t1-quoted")
    assert config.statistical_profile.name == "paired-v2"
    assert config.statistical_profile.alpha == 0.05
    engine = build_report(store, config)
    assert engine["comparisons"][0]["n"] == 48
    report = model_report(store, (ref,), model="scripted", own_group="group_a")
    assert report["H1"]["t1-native"]["n"] == 48
    assert report["H4"]["t1-native"]["n"] == 4
    assert report["H2"]["comparison"]["n"] == 48
    assert report["H3"]["status"] == "in_progress"
    assert len(report["ceiling_effect"]) == 2
    assert report["tables"]

    # A changed route is a changed runtime configuration, even when its
    # subject grid and evaluator are identical. The engine rejects pooling.
    subjects = pilot_subjects()
    worker = ScriptedWorker(store)
    prepared = compile_pilot_plan(
        store, RuntimeProfile(id="scripted", version="1",
                              configuration_ref=str(store.publish_json({"route": "other"}))),
        worker_configuration=worker.configuration("t1-native"), subjects_data=subjects,
        active_subject_ids=(subjects[0].id,),
    )
    by_id = {subject.id: subject for subject in subjects}
    evaluator = GridEvaluator(store, by_id,
                              {subject.id: subject_truth(subject) for subject in subjects})
    other = await execute_plan(
        plan_bytes=prepared.plan_bytes, authorization=prepared.authorization,
        snapshot=prepared.snapshot, store=store,
        workers={arm.id: worker for arm in prepared.snapshot.arms},
        evaluators={item.id: evaluator for item in prepared.snapshot.evaluators},
    )
    assert isinstance(other, RunSucceeded)
    pooled = paired_config(store, (ref, str(other.manifest_ref)),
                           evaluator_id="t1_remnant_inspected",
                           reference_arm="t1-native", candidate_arm="t1-quoted")
    with pytest.raises(ReportError, match="run compatibility drift"):
        build_report(store, pooled)
