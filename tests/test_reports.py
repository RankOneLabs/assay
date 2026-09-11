from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from test_execution import execution_fixture

from assay.canonical import canonical_json
from assay.execution import EvaluationSuccess, RunSucceeded, execute_plan
from assay.models import ReportConfig, StatisticalProfile
from assay.planning import compile_plan
from assay.report_engine import ReportError, build_report, exact_sign_test, persist_report
from assay.reporting import bootstrap_paired, compare_scalar
from assay.store import ObjectStore
from assay.verify import export_bundle, verify_bundle, verify_report


def report_config(result: RunSucceeded, **updates: Any) -> ReportConfig:
    return ReportConfig(
        manifest_refs=(str(result.manifest_ref),),
        record_refs=tuple(sorted(result.manifest.evaluation_records.values())),
        reference_arm="reference",
        candidates=("candidate",),
        evaluator_id="quality",
        metric="scalar",
        scalar_direction="higher_is_better",
        evaluator_repeat_aggregation="mean",
        worker_repeat_aggregation="mean",
        statistical_profile=StatisticalProfile(seed=9, bootstrap_samples=1000),
        engine_version="0.1.0",
    ).model_copy(update=updates)


@pytest.mark.parametrize("n", [2, 9, 10])
async def test_scalar_report_floor_and_offline_recomputation(tmp_path: Path, n: int) -> None:
    fixture = execution_fixture(
        ObjectStore(tmp_path / "store"), subject_ids=tuple(f"s{i}" for i in range(n))
    )
    result = await execute_plan(**fixture.arguments)
    assert isinstance(result, RunSucceeded), result
    config = report_config(result)
    report = build_report(fixture.store, config)
    comparison = report["comparisons"][0]
    assert comparison["effect"] == 1.0
    assert comparison["n"] == n
    assert comparison["confidence_interval"] == ([1.0, 1.0] if n >= 10 else None)
    assert comparison["decision"] == ("improved" if n >= 10 else "descriptive_only")
    assert report["costs"]["coverage"] == "unavailable"
    if n == 10:
        lower = build_report(
            fixture.store, config.model_copy(update={"scalar_direction": "lower_is_better"})
        )
        assert lower["comparisons"][0]["effect"] == 1.0
        assert lower["comparisons"][0]["decision"] == "regressed"
    report_ref = persist_report(fixture.store, config)
    assert verify_report(fixture.store, str(report_ref)) == ()
    exported = export_bundle(fixture.store, str(report_ref), tmp_path / "export")
    assert verify_bundle(exported, str(report_ref)) == ()
    assert canonical_json(report) == exported.read_bytes(report_ref)
    exported.publish_json({"unmanifested": True})
    assert any(e.code == "bundle_closure" for e in verify_bundle(exported, str(report_ref)))


def test_duplicate_low_level_verdict_is_rejected() -> None:
    rows = [("s", "reference", 0, 0, 0.0), ("s", "candidate", 0, 0, 1.0)]
    with pytest.raises(ValueError, match="duplicate"):
        compare_scalar(rows + [rows[1]], reference="reference", candidates=["candidate"])


def test_two_subject_bootstrap_arithmetic_is_separate_from_inference_gate() -> None:
    interval, p = bootstrap_paired([0.0, 2.0], seed=7, samples=10_000)
    assert interval == (0.0, 2.0)
    assert 0.48 < p < 0.52
    assert bootstrap_paired([1.0, 1.0], seed=7, samples=100) == ((1.0, 1.0), 1 / 101)


async def test_report_requires_exact_selection_and_rejects_rerun_pooling(tmp_path: Path) -> None:
    fixture = execution_fixture(ObjectStore(tmp_path), subject_ids=("ok",))
    first = await execute_plan(**fixture.arguments)
    second = await execute_plan(**fixture.arguments)
    assert isinstance(first, RunSucceeded) and isinstance(second, RunSucceeded)
    config = report_config(first)
    with pytest.raises(ReportError, match="selection"):
        build_report(
            fixture.store, config.model_copy(update={"record_refs": config.record_refs[:-1]})
        )
    with pytest.raises(ValidationError, match="unique"):
        ReportConfig.model_validate(
            config.model_dump() | {"record_refs": [*config.record_refs, config.record_refs[0]]}
        )
    merged = config.model_copy(
        update={
            "manifest_refs": (str(first.manifest_ref), str(second.manifest_ref)),
            "record_refs": (*config.record_refs, *second.manifest.evaluation_records.values()),
        }
    )
    with pytest.raises(ReportError, match="duplicate subject/arm"):
        build_report(fixture.store, merged)


async def test_failures_are_reported_before_effects(tmp_path: Path) -> None:
    fixture = execution_fixture(ObjectStore(tmp_path))
    result = await execute_plan(**fixture.arguments)
    assert isinstance(result, RunSucceeded), result
    report = build_report(fixture.store, report_config(result))
    assert report["missingness"]["candidate"]["execution_failures"] == 2
    assert report["comparisons"][0]["n"] == 1
    assert len(report["comparisons"][0]["non_common_subjects"]) == 1


@pytest.mark.parametrize("metric", ["ordinal", "classification"])
async def test_categorical_reports_use_native_labels(tmp_path: Path, metric: str) -> None:
    fixture = execution_fixture(
        ObjectStore(tmp_path), subject_ids=tuple(f"s{i}" for i in range(10))
    )
    store = fixture.store
    declaration = fixture.snapshot.evaluators[0]
    schema = json.loads(store.read_bytes(declaration.payload_schema_ref))
    schema["allOf"][1]["properties"]["verdict"]["properties"]["value"] = {"enum": ["bad", "good"]}
    new_declaration = declaration.model_copy(
        update={"payload_schema_ref": str(store.publish_json(schema))}
    )
    subjects = tuple(
        s.model_copy(
            update={"payload_ref": str(store.publish_json({"subject": s.id, "label": "good"}))}
        )
        for s in fixture.snapshot.subjects
    )
    snapshot = fixture.snapshot.model_copy(
        update={"evaluators": (new_declaration,), "subjects": subjects}
    )
    snapshot_ref = str(store.publish_json(snapshot.model_dump(mode="json")))
    plan = compile_plan(
        snapshot, snapshot_ref=snapshot_ref, worker_repeats=2, jig_revision="55081e8"
    )

    class Labels:
        def configuration(self) -> dict[str, Any]:
            return {"version": "quality-v1"}

        async def evaluate(self, **kwargs: Any) -> EvaluationSuccess:
            return EvaluationSuccess("good" if kwargs["output"]["score"] else "bad")

    args = fixture.arguments | {
        "snapshot": snapshot,
        "plan_bytes": canonical_json(plan.model_dump(mode="json")),
        "evaluators": {"quality": Labels()},
    }
    from assay.canonical import digest_bytes

    args["authorization"] = digest_bytes(args["plan_bytes"])
    result = await execute_plan(**args)
    assert isinstance(result, RunSucceeded), result
    config = report_config(
        result,
        metric=metric,
        scalar_direction=None,
        categories=("bad", "good"),
        positive_label="good" if metric == "classification" else None,
        evaluator_repeat_aggregation="majority",
        worker_repeat_aggregation="majority",
    )
    report = build_report(store, config)
    comparison = report["comparisons"][0]
    assert comparison["improved"] == 10
    assert comparison["ties"] == 0
    assert comparison["p_value"] == 2 / 1024
    assert comparison["decision"] == "improved"
    assert "effect" not in comparison  # no implicit category spacing
    if metric == "classification":
        assert comparison["candidate_metrics"]["accuracy"] == 1.0
        assert comparison["reference_metrics"]["accuracy"] == 0.0
    else:
        assert comparison["candidate_distribution"] == {"good": 10}


def test_sign_test_ties_and_balanced_outcomes() -> None:
    assert exact_sign_test(0, 0) == 1.0
    assert exact_sign_test(5, 5) == 1.0
    assert exact_sign_test(10, 0) == 2 / 1024
