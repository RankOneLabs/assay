"""Offline accounting from published store objects."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from code_extension.classification import DiagnosticAnnotation
from code_extension.ledger import AttemptLedger, build_ledger, terminal_cause
from code_extension.tests.test_code_extension_ledger import _manifest, _outcome, _plan

from assay.models import RunManifest


def test_terminal_conventions_are_explicit() -> None:
    assert terminal_cause("submitted", "") == "normal_submission"
    assert terminal_cause("candidate_failure", "agent_deadline") == "wall_limit"
    for cause in (
        "request_limit",
        "conversation_limit",
        "output_token_limit",
        "turn_tool_call_limit",
        "cell_tool_call_limit",
        "no_tool_call",
        "empty_reply",
        "invalid_tool_call",
        "invalid_submission",
        "turn_limit",
    ):
        assert (
            terminal_cause(
                "candidate_failure", "no_submission", f"agent stopped without submitting: {cause}"
            )
            == cause
        )
    for cause in (
        "symlink_submission",
        "hard_link_submission",
        "binary_payload",
        "oversized_artifact",
        "aggregate_artifact_limit",
        "entry_limit",
        "non_utf8_path",
        "patch_capture_conflict",
        "workspace_capture_permission",
        "invalid_tool_output_encoding",
        "out_of_scope_edit",
        "tampering",
        "traversal",
        "escaping_symlink",
        "storage_exhausted",
        "memory_limit",
    ):
        assert terminal_cause("candidate_failure", cause) == cause
    for cause in ("container_start", "enforcement", "unexpected_exception"):
        assert terminal_cause("infrastructure_failure", cause) == cause
    assert terminal_cause("evaluator_failure", "anything") == "evaluator_failure"
    assert terminal_cause("candidate_failure", "no_submission", "unrecognized") == "unknown"
    assert terminal_cause("candidate_failure", "alien") == "unknown"


def test_planned_missing_and_grading_stopped_work(tmp_path: Path) -> None:
    store, plan, authorization = _plan(tmp_path)
    trajectory_ref = str(store.publish_json({"events": [{"kind": "model_request", "turn": 1}]}))
    execution_ref, _ = _outcome(
        store,
        plan,
        authorization,
        success=False,
        trace={
            "bridge_outcome": {"kind": "candidate_failure", "cause": "agent_deadline"},
            "artifact_refs": {"trajectory.json": trajectory_ref},
        },
    )
    manifest_ref = _manifest(store, plan, authorization, execution_ref, passed=True)
    ledger = build_ledger(plan=plan, manifest_ref=manifest_ref, store=store, judgments={})
    stopped, missing = ledger.rows
    assert stopped.states.agent_started and stopped.states.evaluated
    assert stopped.all_checks_passing and not stopped.states.completed_normally
    assert not stopped.primary_success and stopped.terminal_cause == "wall_limit"
    assert missing.states.planned and missing.states.missing and not missing.states.dispatched
    assert ledger.counts().planned == 2 and ledger.counts().dispatched == 1
    rates = ledger.rates()
    assert (rates.operational_yield.numerator, rates.operational_yield.denominator) == (0, 1)
    assert (rates.primary_task_success.numerator, rates.primary_task_success.denominator) == (0, 1)
    assert rates.conditional_correctness.denominator == 0
    assert rates.invalid == rates.unevaluable == 0


def test_retry_cohorts_and_annotations_do_not_change_measurement(tmp_path: Path) -> None:
    store, plan, authorization = _plan(tmp_path)
    execution_ref, trace_ref = _outcome(store, plan, authorization, success=True, trace={})
    manifest_ref = _manifest(store, plan, authorization, execution_ref, passed=True)
    primary = build_ledger(plan=plan, manifest_ref=manifest_ref, store=store, judgments={})
    annotation = DiagnosticAnnotation(
        label="uncertain",
        assigned_by="analyst",
        evidence_ref=trace_ref,
    )
    second = DiagnosticAnnotation(
        label="ambiguous_fixture",
        assigned_by="analyst",
        evidence_ref=trace_ref,
    )
    manifest = RunManifest.model_validate_json(store.read_bytes(manifest_ref))
    retry_manifest_ref = str(
        store.publish_json(
            manifest.model_copy(update={"run_id": "run-retry"}).model_dump(mode="json")
        )
    )
    retry = build_ledger(
        plan=plan,
        manifest_ref=retry_manifest_ref,
        store=store,
        judgments={},
        annotations={plan.cells[0].id: (annotation, second)},
        retry_of={plan.cells[0].id: primary.rows[0].attempt_id},
    )
    assert retry.rows[0].attempt_id != primary.rows[0].attempt_id
    assert retry.rows[0].axes == primary.rows[0].axes
    assert retry.rows[0].states == primary.rows[0].states
    assert len(retry.rows[0].annotations) == 2
    assert retry.cohorts()[f"retry:{primary.rows[0].attempt_id}"].rates() == primary.rates()
    combined = AttemptLedger(primary.rows + (retry.rows[0],))
    with pytest.raises(ValueError, match="mixed retry cohorts"):
        combined.rates()
    cohorts = combined.cohorts()
    assert len(cohorts["primary"].rows) == 2
    assert len(cohorts[f"retry:{primary.rows[0].attempt_id}"].rows) == 1
    assert cohorts["primary"].rates().operational_yield.denominator == 1
    assert cohorts[f"retry:{primary.rows[0].attempt_id}"].rates().operational_yield.denominator == 1


def test_infrastructure_invalid_and_unevaluable_are_visible(tmp_path: Path) -> None:
    store, plan, authorization = _plan(tmp_path)
    execution_ref, _ = _outcome(
        store,
        plan,
        authorization,
        success=False,
        trace={
            "bridge_outcome": {"kind": "infrastructure_failure", "cause": "enforcement"},
        },
    )
    manifest_ref = _manifest(store, plan, authorization, execution_ref, passed=False)
    ledger = build_ledger(plan=plan, manifest_ref=manifest_ref, store=store, judgments={})
    rates = ledger.rates()
    assert rates.invalid == 1 and rates.unevaluable == 1
    assert rates.operational_yield.denominator == 1
    assert rates.primary_task_success.denominator == 0


def test_judgment_cannot_override_mechanical_or_passed(tmp_path: Path) -> None:
    from code_extension.classification import operator_category

    store, plan, authorization = _plan(tmp_path)
    execution_ref, trace_ref = _outcome(
        store,
        plan,
        authorization,
        success=False,
        trace={
            "bridge_outcome": {"kind": "candidate_failure", "cause": "agent_deadline"},
        },
    )
    manifest_ref = _manifest(store, plan, authorization, execution_ref, passed=False)
    judgment = operator_category(
        "code_generation_defect", assigned_by="analyst", trace_digest=trace_ref
    )
    with pytest.raises(ValueError, match="mechanical category"):
        build_ledger(
            plan=plan,
            manifest_ref=manifest_ref,
            store=store,
            judgments={plan.cells[0].id: judgment},
        )
    success_ref, success_trace = _outcome(store, plan, authorization, success=True, trace={})
    passed_ref = _manifest(store, plan, authorization, success_ref, passed=True)
    passed_judgment = operator_category(
        "code_generation_defect",
        assigned_by="analyst",
        trace_digest=success_trace,
    )
    with pytest.raises(ValueError, match="passed attempt"):
        build_ledger(
            plan=plan,
            manifest_ref=passed_ref,
            store=store,
            judgments={plan.cells[0].id: passed_judgment},
        )


def test_separate_feature_build_and_regression_axes(tmp_path: Path) -> None:
    store, plan, authorization = _plan(tmp_path)
    execution_ref, trace_ref = _outcome(store, plan, authorization, success=True, trace={})
    manifest_ref = _manifest(store, plan, authorization, execution_ref, passed=True)
    manifest = RunManifest.model_validate_json(store.read_bytes(manifest_ref))
    record_ref = next(iter(manifest.evaluation_records.values()))
    record = json.loads(store.read_bytes(record_ref))
    detail_ref = record["payload"]["detail_refs"][0]
    detail = json.loads(store.read_bytes(detail_ref))
    detail["groups"]["new_behavior"] = {"status": "failed", "cause": "group_failure"}
    new_detail_ref = str(store.publish_json(detail))
    record["payload"]["detail_refs"] = [new_detail_ref]
    record["verdict"]["value"] = "incorrect"
    new_record_ref = str(store.publish_json(record))
    changed = manifest.model_copy(
        update={"evaluation_records": {next(iter(manifest.evaluation_records)): new_record_ref}}
    )
    changed_ref = str(store.publish_json(changed.model_dump(mode="json")))
    from code_extension.classification import operator_category

    judgment = operator_category(
        "code_generation_defect", assigned_by="analyst", trace_digest=trace_ref
    )
    row = build_ledger(
        plan=plan, manifest_ref=changed_ref, store=store, judgments={plan.cells[0].id: judgment}
    ).rows[0]
    assert row.axes.feature == "failed" and row.axes.regression == "passed"
    assert row.axes.build == "unavailable"
    build_detail = json.loads(store.read_bytes(detail_ref))
    build_detail["preflight"] = {"status": "failed", "cause": "typecheck_failure"}
    for group in build_detail["groups"].values():
        group["status"] = "unavailable"
        group["cause"] = "typecheck_failure"
    record["payload"]["detail_refs"] = [str(store.publish_json(build_detail))]
    build_record_ref = str(store.publish_json(record))
    build_manifest = manifest.model_copy(
        update={
            "evaluation_records": {next(iter(manifest.evaluation_records)): build_record_ref},
        }
    )
    build_manifest_ref = str(store.publish_json(build_manifest.model_dump(mode="json")))
    build_row = build_ledger(
        plan=plan,
        manifest_ref=build_manifest_ref,
        store=store,
        judgments={plan.cells[0].id: judgment},
    ).rows[0]
    assert build_row.axes.build == "failed"
    assert build_row.axes.feature == "unavailable"
    assert build_row.axes != row.axes
