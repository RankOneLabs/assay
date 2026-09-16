from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import paa_contracts
import pytest

from assay._version import __version__
from assay.canonical import canonical_json, digest_bytes
from assay.execution import (
    Accounting,
    EvaluationFailed,
    EvaluationSuccess,
    RunSucceeded,
    WorkerFailure,
    WorkerResult,
    WorkerSuccess,
    execute_plan,
)
from assay.investigations.consistency import (
    CATEGORIES,
    TASKS,
    CodingTask,
    StructuralEvaluator,
    materialize_consistency,
)
from assay.models import EvaluationCoordinate, Exclusion, ReportConfig, StatisticalProfile
from assay.planning import compile_plan
from assay.report_engine import build_report, persist_report
from assay.store import ObjectStore
from assay.verify import (
    export_bundle,
    verify_bundle,
    verify_manifest,
    verify_report,
    verify_snapshot,
)


class FixtureWorker:
    """Synthetic acceptance worker; it is never evidence about an actual coding agent."""

    def __init__(self) -> None:
        self.failed = False

    def configuration(self, arm_id: str) -> dict[str, Any]:
        return {
            "id": "local-fixture",
            "version": "1",
            "failure": "first-record-decoding-clean-call",
        }

    async def run(self, *, input_value: Any, arm_id: str) -> WorkerResult:
        if arm_id == "clean" and input_value["task"]["id"] == TASKS[1].id and not self.failed:
            self.failed = True
            return WorkerFailure("InjectedFailure", "acceptance failure")
        task = next(task for task in TASKS if task.id == input_value["task"]["id"])
        source = task.reused_source if arm_id == "clean" else task.duplicated_source
        return WorkerSuccess({"source": source})


def contracts() -> dict[str, dict[str, Any]]:
    return {
        name: paa_contracts.load_schema(name)
        for name in ("paa-task", "paa-evidence-record", "paa-operating-record")
    }


@pytest.mark.asyncio
async def test_local_acceptance_with_failure_exclusion_and_separate_repeats(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    worker = FixtureWorker()
    evaluator = StructuralEvaluator()
    snapshot = materialize_consistency(
        store,
        worker_configuration=worker.configuration("clean"),
        evaluator=evaluator,
        schemas=contracts(),
        tasks=TASKS[:2],
        evaluator_repeats=2,
    )
    verify_snapshot(store, snapshot)
    assert len(snapshot.subjects) == 2
    for subject in snapshot.subjects:
        assert subject.digest == subject.payload_ref
        base = json.loads(store.read_bytes(subject.payload_ref))
        assert "reused_source" not in base and "duplicated_source" not in base
        pair = [r for r in snapshot.realizations if r.subject_id == subject.id]
        assert pair[0].artifact_ref != pair[1].artifact_ref
    plan = compile_plan(
        snapshot,
        snapshot_ref=str(store.publish_json(snapshot.model_dump(mode="json"))),
        worker_repeats=2,
        jig_revision="local-fixture",
        concurrency=2,
        exclusions=(
            Exclusion(
                subject_id=TASKS[1].id,
                arm_id="inconsistent",
                classification="fixture",
                reason="predeclared acceptance exclusion",
            ),
        ),
    )
    assert len(plan.cells) == 6 and len(plan.evaluations) == 12
    plan_bytes = canonical_json(plan.model_dump(mode="json"))
    result = await execute_plan(
        plan_bytes=plan_bytes,
        authorization=digest_bytes(plan_bytes),
        snapshot=snapshot,
        store=store,
        workers={"clean": worker, "inconsistent": worker},
        evaluators={"abstraction": evaluator},
    )
    assert isinstance(result, RunSucceeded), result
    # The one failed worker cell has two evaluations planned against it that
    # are now genuinely unavailable, so the manifest is honestly incomplete
    # -- but self-consistent: verification reports only that expected flag.
    assert result.manifest.status == "incomplete"
    assert [f.code for f in verify_manifest(store, str(result.manifest_ref))] == ["incomplete_run"]
    executions = [
        json.loads(store.read_bytes(ref)) for ref in result.manifest.execution_records.values()
    ]
    assert sum(record["status"] == "failed" for record in executions) == 1
    evidence = [
        json.loads(store.read_bytes(ref)) for ref in result.manifest.evaluation_records.values()
    ]
    assert sum(record.get("error_type") == "ExecutionUnavailable" for record in evidence) == 2
    verdicts = [record for record in evidence if "verdict" in record]
    assert len(verdicts) == 10
    assert {record["payload"]["evaluator_repeat"] for record in verdicts} == {0, 1}
    assert {record["payload"]["worker_repeat"] for record in verdicts} == {0, 1}
    assert {record["verdict"]["value"] for record in verdicts} == {"duplicated", "reused"}
    config = ReportConfig(
        manifest_refs=(str(result.manifest_ref),),
        record_refs=tuple(sorted(result.manifest.evaluation_records.values())),
        reference_arm="clean",
        candidates=("inconsistent",),
        evaluator_id="abstraction",
        metric="ordinal",
        categories=CATEGORIES,
        evaluator_repeat_aggregation="median",
        worker_repeat_aggregation="median",
        statistical_profile=StatisticalProfile(seed=7, bootstrap_samples=100),
        engine_version=__version__,
    )
    report = build_report(store, config)
    assert report["metric"] == "ordinal"
    assert report["missingness"] == {
        "clean": {"execution_failures": 1, "evaluation_failures": 2, "incomplete_subjects": 1},
        "inconsistent": {"excluded_subjects": 1},
    }
    assert len(report["exclusions"]) == 1
    assert report["exclusions"][0]["subject_id"] == TASKS[1].id
    comparison = report["comparisons"][0]
    assert comparison["n"] == 1
    assert comparison["test"] == "exact_paired_sign"
    assert comparison["reference_distribution"] == {"reused": 1}
    assert comparison["candidate_distribution"] == {"duplicated": 1}
    assert comparison["regressed"] == 1 and comparison["improved"] == 0
    assert comparison["decision"] == "descriptive_only"
    assert comparison["p_value"] is None and comparison["confidence_interval"] is None
    assert "effect" not in comparison
    assert len(comparison["non_common_subjects"]) == 1
    report_ref = persist_report(store, config)
    assert verify_report(store, str(report_ref)) == ()
    assert store.read_bytes(report_ref) == canonical_json(report)
    # An unrelated source-store object must not leak into the report export.
    unrelated = store.publish_json({"unrelated": "not evidence for this report"})
    exported = export_bundle(store, str(report_ref), tmp_path / "export")
    assert verify_bundle(exported, str(report_ref)) == ()
    with pytest.raises(FileNotFoundError):
        exported.read_bytes(unrelated)
    exported_config = ReportConfig.model_validate_json(exported.read_bytes(report["config_ref"]))
    assert canonical_json(build_report(exported, exported_config)) == exported.read_bytes(
        report_ref
    )


class Judge:
    def __init__(self, result: EvaluationSuccess | EvaluationFailed) -> None:
        self.calls = 0
        self.result = result

    def configuration(self) -> dict[str, Any]:
        return {"id": "fake-ambiguity-judge", "version": "1"}

    async def judge(self, *, task: CodingTask, source: str) -> EvaluationSuccess | EvaluationFailed:
        self.calls += 1
        return self.result


@pytest.mark.asyncio
async def test_structural_analysis_uses_judge_only_for_ambiguity() -> None:
    judge = Judge(EvaluationSuccess("reused", detail={"reason": "alias resolves to helper"}))
    evaluator = StructuralEvaluator(judge)
    coordinate = EvaluationCoordinate(
        cell_id="s:clean:w0", evaluator_id="abstraction", evaluator_repeat=0
    )
    task = TASKS[0]
    for source, expected in (
        (task.reused_source, "reused"),
        (task.duplicated_source, "duplicated"),
        ("def implement(value):\n    return normalize_name(value.strip())\n", "mixed"),
    ):
        result = await evaluator.evaluate(
            input_value={"task": task.model_dump()},
            output={"source": source},
            coordinate=coordinate,
        )
        assert isinstance(result, EvaluationSuccess)
        assert result.verdict == expected
    assert judge.calls == 0
    result = await evaluator.evaluate(
        input_value={"task": task.model_dump()},
        output={"source": "def implement(value):\n    f = normalize_name\n    return f(value)\n"},
        coordinate=coordinate,
    )
    assert isinstance(result, EvaluationSuccess) and result.detail["route"] == "judge"
    assert judge.calls == 1


@pytest.mark.asyncio
async def test_ambiguous_and_invalid_outputs_are_failures() -> None:
    coordinate = EvaluationCoordinate(
        cell_id="s:clean:w0", evaluator_id="abstraction", evaluator_repeat=0
    )
    for source, error_type in (
        ("def implement(value): return value", "AmbiguousStructure"),
        ("invalid python !", "InvalidOutput"),
    ):
        result = await StructuralEvaluator().evaluate(
            input_value={"task": TASKS[0].model_dump()},
            output={"source": source},
            coordinate=coordinate,
        )
        assert isinstance(result, EvaluationFailed) and result.error_type == error_type


def test_all_stakes_families_materialize_without_provider_calls(tmp_path: Path) -> None:
    snapshot = materialize_consistency(
        ObjectStore(tmp_path),
        worker_configuration={"id": "unused", "version": "1"},
        evaluator=StructuralEvaluator(),
        schemas=contracts(),
    )
    assert {subject.partition for subject in snapshot.subjects} == {
        "cosmetic",
        "architectural",
        "semantic",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_success", [False, True])
async def test_judge_failures_preserve_attempt_accounting(invalid_success: bool) -> None:
    accounting = Accounting(usage={"input_tokens": 17, "output_tokens": 2})
    result = (
        EvaluationSuccess("undeclared", accounting=accounting)
        if invalid_success
        else EvaluationFailed("JudgeError", "failed", accounting=accounting)
    )
    evaluator = StructuralEvaluator(Judge(result))
    outcome = await evaluator.evaluate(
        input_value={"task": TASKS[0].model_dump()},
        output={"source": "def implement(value): return value"},
        coordinate=EvaluationCoordinate(
            cell_id="s:clean:w0",
            evaluator_id="abstraction",
            evaluator_repeat=0,
        ),
    )
    assert isinstance(outcome, EvaluationFailed)
    assert outcome.accounting == accounting
    assert outcome.error_type == ("InvalidJudgeVerdict" if invalid_success else "JudgeError")
