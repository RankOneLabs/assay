"""Pilot-specific inference is checked independently of the shared report engine."""

import base64
import json
from pathlib import Path

import pytest

from assay.execution import RunFailed, RunSucceeded, execute_plan
from assay.models import RunManifest, RuntimeProfile
from assay.report_engine import ReportError, build_report
from assay.store import ObjectStore
from verification_pilot.analysis import (
    MeasureCell,
    h1_sign_test,
    h2_paired_sign_test,
    h4_rename_pairs,
    result_tables,
    wide_search_ceiling,
)
from verification_pilot.observations import Measured, TurnMeasure
from verification_pilot.report import (
    Observation,
    cross_model_table,
    first_inspection_is_wide_symbol_search,
    h1_ownership_gap,
    h4_own_vs_teammate,
    model_report,
    paired_config,
)
from verification_pilot.run import (
    GridEvaluator,
    ScriptedWorker,
    run_scripted,
    save_run_trace,
    subject_truth,
)
from verification_pilot.study import compile_pilot_plan, pilot_subjects


def _cell(subject: str, migration: str, group: str, arm: str, *,
          gap: float = 1.0, inspected: bool = True,
          wide: bool = False) -> MeasureCell:
    measures = tuple(TurnMeasure("T1", "inspection", name, Measured("measured", item))
                     for name, item in (("ownership_gap", gap),
                                        ("remnant_path_inspected", inspected),
                                        ("first_inspection_is_wide_search", wide)))
    return MeasureCell("fixture", subject, migration, group, arm, measures)


def test_analysis_h1_n16_exact_sign_and_missing_boundary() -> None:
    rows = [_cell(f"s{i}", f"m{i // 4}", "group_a", "t1-native",
                  gap=1 if i < 16 else -1) for i in range(16)]
    result = h1_sign_test(rows, "t1-native")
    assert result["n"] == 16
    assert result["p_value"] == 2 / 2**16
    assert h1_sign_test(rows[:-1], "t1-native")["p_value"] is None
    assert h1_sign_test([*rows[:-1], _cell("s15", "m3", "group_a",
                                            "t1-native", gap=-1)], "t1-native")[
        "p_value"] == 2 * (1 + 16) / 2**16


def test_analysis_h2_paired_sign_uses_matching_subjects() -> None:
    rows: list[MeasureCell] = []
    for i in range(4):
        rows.extend((_cell(f"s{i}", "m", "group_a", "t1-native", gap=0),
                     _cell(f"s{i}", "m", "group_a", "t1-quoted",
                           gap=1 if i < 3 else 0)))
    result = h2_paired_sign_test(rows)
    assert (result["n"], result["improved"], result["ties"]) == (4, 3, 1)
    assert result["p_value"] == 0.25


def test_analysis_h4_four_pair_floor_boundary() -> None:
    rows = [_cell(f"{migration}-{group}", migration, group, "t1-native",
                  inspected=group == "group_a")
            for migration in ("a", "b", "c", "d")
            for group in ("group_a", "group_b", "group_c")]
    result = h4_rename_pairs(rows, "t1-native", "group_a")
    assert result["n"] == 4
    assert result["p_value"] == result["p_floor"] == 0.125
    assert result["decision"] == "descriptive_only"
    assert h4_rename_pairs(rows[:-3], "t1-native", "group_a")["p_value"] is None


def test_analysis_wide_search_strict_half_boundary_and_tables() -> None:
    rows = [_cell(f"s{i}", "m", "group_a", "t1-native", wide=i < 2)
            for i in range(4)]
    assert wide_search_ceiling(rows, "t1-native")["exceeds_half"] is False
    assert wide_search_ceiling(rows[:-1], "t1-native")["exceeds_half"] is True
    tables = result_tables(rows)
    assert tables["routes"][0]["ceiling"]["t1-native"]["share"] == 0.5
    assert any(row["measure"] == "first_inspection_is_wide_search"
               for row in tables["measures"])


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


def test_failed_cell_archive_keeps_partial_trajectory(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "store")
    subject = pilot_subjects()[0]
    trajectory = {"turns": [{
        "turn": "T1", "stop_cause": "deadline", "patch_ref": "sha256:partial",
        "tree_digest": "observed-tree", "baseline_tree_digest": "baseline-tree",
        "submission": None, "workspace_diff": "", "tool_calls": [],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2,
                  "requests": 1, "cost_usd": 0.12},
    }]}
    trajectory_bytes = json.dumps(trajectory).encode()
    raw_ref = store.publish_json({
        "content_base64": base64.b64encode(trajectory_bytes).decode("ascii"),
    })
    trace_ref = store.publish_json({"artifact_refs": {"trajectory.json": str(raw_ref)}})
    cell_id = f"{subject.id}:t1-native:w0"
    record_ref = store.publish_json({
        "status": "failed", "output_ref": None, "trace_ref": str(trace_ref),
    })
    manifest = RunManifest(
        run_id="failed-cell", plan_ref=str(store.publish_json({"plan": "test"})),
        status="complete", execution_records={cell_id: str(record_ref)},
        evaluation_records={}, missing_coordinates=(),
    )
    manifest_ref = store.publish_json(manifest.model_dump(mode="json"))
    result = RunFailed("DeadlineExceeded", "deadline", manifest, manifest_ref)

    archive = save_run_trace(store, result, tmp_path / "raw" / "runs",
                             {subject.id: subject})

    assert archive is not None
    index = json.loads((archive / "index.json").read_text())
    assert index[cell_id]["status"] == "failed"
    assert index[cell_id]["trajectory"] == "001-trajectory.json"
    assert json.loads((archive / "traces" / "001-trajectory.json").read_bytes()) == trajectory
    assert index[cell_id]["measures"] == "001-measures.json"
    measures = json.loads((archive / "traces" / "001-measures.json").read_text())
    assert {item["family"] for item in measures} == {"inspection"}
    assert next(item["result"]["value"] for item in measures
                if item["name"] == "stop_cause") == "deadline"
    assert next(item["result"]["value"] for item in measures
                if item["name"] == "cost_usd") == 0.12


@pytest.mark.asyncio
async def test_scripted_grid_builds_paired_h2_and_separate_model_report(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "store")
    _, run = await run_scripted(store)
    assert isinstance(run, RunSucceeded)
    archive = tmp_path / "runs" / run.manifest.run_id
    assert (archive / "manifest.json").read_bytes() == store.read_bytes(run.manifest_ref)
    assert list((archive / "traces").glob("*-trajectory.json"))
    assert list((archive / "traces").glob("*-measures.json"))
    index = json.loads((archive / "index.json").read_text())
    first = next(iter(index.values()))
    measures = json.loads((archive / "traces" / first["measures"]).read_text())
    assert {item["family"] for item in measures} == {"inspection", "claim", "verdict"}
    assert {item["turn"] for item in measures} == {"T1", "T2", "T3"}
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
