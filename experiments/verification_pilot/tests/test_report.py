"""Pilot-specific inference is checked independently of the shared report engine."""

from pathlib import Path

import pytest

from assay.execution import RunSucceeded, execute_plan
from assay.models import RuntimeProfile
from assay.report_engine import ReportError, build_report
from assay.store import ObjectStore
from verification_pilot.report import (
    Observation,
    cross_model_table,
    first_inspection_is_wide_symbol_search,
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
                    "t1-native", "pilot_judge", value, "group_a")
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
                    "t1-native", "t1_remnant_inspected", value, "group_a")
        for migration in ("a", "b", "c", "d")
        for group, value in (("group_a", "1"), ("group_b", "0"))
    ]
    result = h4_own_vs_teammate(rows, "t1-native", own_group="group_a")
    assert result["n"] == 4
    assert result["mean_difference"] == 1
    assert result["p_value"] is None
    assert all(pair["own"] == 1 and pair["teammate"] == 0 for pair in result["pairs"])


def test_h4_rejects_an_own_group_different_from_subject_assignment() -> None:
    row = Observation("route", "s", "migration", "group_b", 0, 2,
                      "t1-native", "t1_remnant_inspected", "1", "group_a")
    with pytest.raises(ValueError, match="subject payload assignment"):
        h4_own_vs_teammate((row,), "t1-native", own_group="group_b")


def test_ceiling_uses_first_successful_inspection_of_old_symbol() -> None:
    failed = {"name": "search_files", "arguments": {"scope": "./", "query": "oldName"},
              "exit_code": 1}
    wide = {"name": "search_files", "arguments": {"scope": ".", "query": "oldName"},
            "exit_code": 0}
    read = {"name": "read_file", "arguments": {"path": "src/a.ts"}, "exit_code": 0}
    assert first_inspection_is_wide_symbol_search({"tool_calls": [failed, wide]}, "oldName")
    assert not first_inspection_is_wide_symbol_search({"tool_calls": [read, wide]}, "oldName")
    assert not first_inspection_is_wide_symbol_search(
        {"tool_calls": [{**wide, "arguments": {"scope": "src", "query": "oldName"}}]},
        "oldName",
    )
    assert not first_inspection_is_wide_symbol_search(
        {"tool_calls": [{**wide, "arguments": {"scope": ".", "query": "newName"}}]},
        "oldName",
    )


def test_cross_model_table_keeps_routes_separate() -> None:
    first = {key: key for key in ("H1", "H2", "H3", "H4", "ceiling_effect", "cost")}
    second = {**first, "H2": "second route"}
    table = cross_model_table({"z-route": second, "a-route": first})
    assert [row["model"] for row in table] == ["a-route", "z-route"]
    assert table[0]["H2"] == "H2"
    assert table[1]["H2"] == "second route"


@pytest.mark.asyncio
async def test_scripted_grid_builds_paired_h2_and_separate_model_report(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "store")
    _, run = await run_scripted(store)
    assert isinstance(run, RunSucceeded)
    archive = tmp_path / "runs" / run.manifest.run_id
    assert (archive / "manifest.json").read_bytes() == store.read_bytes(run.manifest_ref)
    assert list((archive / "traces").glob("*-trajectory.json"))
    ref = str(run.manifest_ref)
    config = paired_config(store, (ref,), evaluator_id="pilot_judge",
                           reference_arm="t1-native", candidate_arm="t1-quoted")
    assert config.statistical_profile.name == "paired-v2"
    assert config.statistical_profile.alpha == 0.05
    engine = build_report(store, config)
    assert engine["comparisons"][0]["n"] == 12
    report = model_report(store, (ref,), model="scripted", own_group="group_a")
    assert report["H1"]["t1-native"]["n"] == 12
    assert report["H4"]["t1-native"]["n"] == 0
    assert report["H2"]["comparison"]["n"] == 12
    assert report["H3"]["status"] == "in_progress"
    assert len(report["ceiling_effect"]) == 2
    assert report["tables"]
    assert {row["turn"] for row in report["tables"] if row["evaluator_id"] == "pilot_judge"} == {
        "t1"
    }

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
                           evaluator_id="pilot_judge",
                           reference_arm="t1-native", candidate_arm="t1-quoted")
    with pytest.raises(ReportError, match="run compatibility drift"):
        build_report(store, pooled)
