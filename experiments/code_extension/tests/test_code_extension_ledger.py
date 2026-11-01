"""Ledger coverage of settled, judged, and unstarted attempts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from code_extension.classification import (
    CandidateStopped,
    EvaluatorVerdict,
    GroupVerdict,
    HarnessOrProviderFailure,
    NeedsOperatorJudgment,
    Timeout,
    classify,
    operator_category,
    parse_category,
)
from code_extension.evaluation import evaluation_detail
from code_extension.ledger import _Detail, build_ledger
from code_extension.study import plan_study
from code_extension.tests.test_code_extension_study import PlanWorker, _pilot, _two_arm_fixture
from pydantic import ValidationError

from assay.execution import Accounting
from assay.investigations.workflow_correctness import DockerWorkflowRunner, WorkflowRunnerSettings
from assay.models import (
    ExecutionCeiling,
    ExecutionOutcome,
    ExecutionPlanV3,
    RunManifest,
    RuntimeProfile,
    parse_execution_plan,
)
from assay.store import ObjectStore


def _plan(tmp_path: Path) -> tuple[ObjectStore, ExecutionPlanV3, str]:
    store, pilot = _pilot(tmp_path)
    fixture = _two_arm_fixture(store, pilot)
    image = fixture.manifest.observed_runtime_image_digest
    prepared = plan_study(
        store, fixture, workers={arm: PlanWorker() for arm in fixture.manifest.arm_set.arm_ids},
        runner=DockerWorkflowRunner(WorkflowRunnerSettings(image=image, toolchain="bun")),
        runtime=RuntimeProfile(
            id="pier", version="scripted", configuration_ref=str(store.publish_json({"v": 1})),
        ),
        image=image, routing_digest=fixture.manifest.routing_config_digest, repeats=1,
        ceiling=ExecutionCeiling(max_cells=2, max_wall_time_seconds=600, max_fleet_occupancy=1),
    )
    plan = parse_execution_plan(json.loads(prepared.plan_bytes))
    assert isinstance(plan, ExecutionPlanV3)
    return store, plan, prepared.authorization


def _outcome(
    store: ObjectStore, plan: ExecutionPlanV3, authorization: str, *,
    success: bool, trace: dict[str, object],
) -> tuple[str, str]:
    cell = plan.cells[0]
    trace_ref = str(store.publish_json(trace))
    output_ref = None
    if success:
        output_ref = str(store.publish_json({
            "patch_ref": str(store.publish_json({"patch": "retained"})),
            "raw_trajectory_ref": str(store.publish_json({"turns": []})),
            "result_ref": str(store.publish_json({"result": "retained"})),
        }))
    outcome = ExecutionOutcome(
        run_id="run", plan_ref=authorization, coordinate=cell,
        started_at="2026-10-29T00:00:00Z", completed_at="2026-10-29T00:00:01Z",
        status="succeeded" if success else "failed", input_ref=cell.realization_ref,
        output_ref=output_ref, trace_ref=trace_ref,
        error_type=None if success else "CandidateFailure",
        error_message=None if success else "no_submission",
    )
    return str(store.publish_json(outcome.model_dump(mode="json"))), trace_ref


def _manifest(
    store: ObjectStore, plan: ExecutionPlanV3, authorization: str,
    execution_ref: str, *, passed: bool,
) -> str:
    cell = plan.cells[0]
    evaluation_records: dict[str, str] = {}
    if passed:
        detail_ref = str(store.publish_json(evaluation_detail(
            groups={
                "visible_regression": {"status": "passed", "cause": None},
                "hidden_regression": {"status": "passed", "cause": None},
                "new_behavior": {"status": "passed", "cause": None},
            },
            empty_patch=False,
            preflight={"status": "passed", "cause": None},
            rejected_changes=(),
            evaluator_record_ref=str(store.publish_json({"grader_cache_key": "k"})),
        )))
        evaluation_records[plan.evaluations[0].id] = str(store.publish_json({
            "record_schema": "paa-evidence-record/0.3.0-draft",
            "verdict": {"value": "correct", "reason_codes": []},
            "payload": {"detail_refs": [detail_ref]},
        }))
    manifest = RunManifest(
        run_id="run", plan_ref=authorization, status="incomplete",
        execution_records={cell.id: execution_ref}, evaluation_records=evaluation_records,
        missing_coordinates=(plan.cells[1].id,),
    )
    return str(store.publish_json(manifest.model_dump(mode="json")))


def test_mechanical_map_keeps_timeout_and_invalid_distinction() -> None:
    assert isinstance(parse_category({"tag": "timeout"}), Timeout)
    with pytest.raises(ValueError):
        parse_category({"tag": "ninth_category"})
    with pytest.raises(ValueError):
        parse_category({"tag": "wrong_abstraction_or_plan"})
    assert isinstance(classify(CandidateStopped("agent_deadline"), None), Timeout)
    assert classify(CandidateStopped("no_submission"), None) == NeedsOperatorJudgment(
        "invalid_or_incomplete"
    )
    assert classify(
        CandidateStopped("no_submission"), EvaluatorVerdict(
            "incorrect", (GroupVerdict("failed", "typecheck_failure"),)
        )
    ) == NeedsOperatorJudgment("invalid_or_incomplete")


def test_ledger_keeps_unstarted_cell_and_passing_candidate(tmp_path: Path) -> None:
    store, plan, authorization = _plan(tmp_path)
    execution_ref, _ = _outcome(store, plan, authorization, success=True, trace={})
    manifest_ref = _manifest(store, plan, authorization, execution_ref, passed=True)
    ledger = build_ledger(plan=plan, manifest_ref=manifest_ref, store=store, judgments={})
    assert len(ledger.rows) == len(plan.cells) == 2
    assert ledger.counts().attempted == 2
    assert ledger.counts().completed == ledger.counts().passed == 1
    assert ledger.rows[0].category is None
    assert ledger.rows[0].reference.resolve(store)[0] is not None
    missing = ledger.rows[1]
    assert isinstance(missing.category, HarnessOrProviderFailure)
    assert missing.reference.resolve(store) == (None, None)
    assert missing.reference.manifest_ref == manifest_ref
    assert missing.accounting == Accounting()


def test_operator_judgment_is_required_and_bound_to_trace(tmp_path: Path) -> None:
    store, plan, authorization = _plan(tmp_path)
    partial_patch_ref = str(store.publish_json({"partial_patch": "retained"}))
    trajectory_ref = str(store.publish_json({"turns": []}))
    execution_ref, trace_ref = _outcome(
        store, plan, authorization, success=False,
        trace={
            "bridge_outcome": {"kind": "candidate_failure", "cause": "no_submission"},
            "artifact_refs": {
                "stopped/candidate.patch": partial_patch_ref,
                "trajectory.json": trajectory_ref,
            },
        },
    )
    manifest_ref = _manifest(store, plan, authorization, execution_ref, passed=False)
    with pytest.raises(ValueError, match="operator judgment required"):
        build_ledger(plan=plan, manifest_ref=manifest_ref, store=store, judgments={})
    wrong = operator_category(
        "code_generation_defect", assigned_by="analyst", trace_digest="sha256:" + "a" * 64
    )
    with pytest.raises(ValueError, match="wrong trace"):
        build_ledger(
            plan=plan, manifest_ref=manifest_ref, store=store,
            judgments={plan.cells[0].id: wrong},
        )
    judgment = operator_category(
        "code_generation_defect", assigned_by="analyst", trace_digest=trace_ref
    )
    ledger = build_ledger(
        plan=plan, manifest_ref=manifest_ref, store=store,
        judgments={plan.cells[0].id: judgment},
    )
    assert ledger.rows[0].category == judgment
    assert ledger.rows[0].distinction == "invalid_or_incomplete"
    assert ledger.rows[0].reference.resolve(store)[1] is not None
    assert ledger.rows[0].reference.patch_ref == partial_patch_ref
    assert ledger.rows[0].reference.raw_trajectory_ref == trajectory_ref


def test_evaluator_detail_is_exactly_what_the_ledger_reads() -> None:
    """Producer and reader must not drift apart again.

    The ledger silently lost the build and scope evidence once because the
    evaluator kept it in a referenced record this object only pointed at.
    """
    rejected = ({"path": "tests/visible/smoke.test.ts", "reason": "not_writable"},)
    produced = evaluation_detail(
        groups={"new_behavior": {"status": "passed", "cause": None}},
        empty_patch=False,
        preflight={"status": "passed", "cause": None},
        rejected_changes=rejected,
        evaluator_record_ref="sha256:" + "a" * 64,
    )
    detail = _Detail.model_validate(produced)
    assert detail.preflight == {"status": "passed", "cause": None}
    assert detail.rejected_changes == rejected
    assert detail.evaluator_record_ref == "sha256:" + "a" * 64
    # A field the evaluator starts emitting without the ledger declaring it now
    # fails loudly, rather than being dropped and changing an outcome axis.
    with pytest.raises(ValidationError):
        _Detail.model_validate({**produced, "attribution": "resolved"})
