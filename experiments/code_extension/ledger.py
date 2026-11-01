"""One inspectable row for each planned extension attempt, including unsettled cells."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from assay.canonical import canonical_json, digest_bytes
from assay.execution import Accounting
from assay.models import ExecutionOutcome, ExecutionPlanV3, RunManifest
from assay.pier_protocol import CandidateCause, InfrastructureCause
from assay.store import ObjectStore
from code_extension.classification import (
    AttemptStates,
    CandidateStopped,
    CoreStopped,
    DiagnosticAnnotation,
    EvaluatorVerdict,
    FailureCategory,
    GroupVerdict,
    HarnessOrProviderFailure,
    InfrastructureStopped,
    NeedsOperatorJudgment,
    NotStarted,
    OperatorCategory,
    OutcomeAxes,
    Passed,
    RateRecord,
    StopCause,
    Submitted,
    TerminalCause,
    TerminalKind,
    Timeout,
    classify,
)


class _Wire(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _Output(_Wire):
    patch_ref: str
    raw_trajectory_ref: str
    result_ref: str


class _BridgeOutcome(_Wire):
    kind: Literal["candidate_failure", "infrastructure_failure"]
    cause: str
    detail: str = ""


class _Trace(_Wire):
    bridge_outcome: _BridgeOutcome | None = None
    artifact_refs: dict[str, str] = {}
    rejection_reason: str | None = None


class _VerdictValue(_Wire):
    value: Literal["correct", "incorrect", "unavailable"]
    reason_codes: tuple[str, ...] = ()


class _Payload(_Wire):
    detail_refs: tuple[str, ...] = ()


class _Evidence(_Wire):
    verdict: _VerdictValue
    payload: _Payload


class _EvidenceMarker(_Wire):
    record_schema: str | None = None


class _Group(_Wire):
    status: Literal["passed", "failed", "unavailable"]
    cause: str | None = None


class _Detail(_Wire):
    """The evaluator's per-cell detail object, mirrored field for field.

    Strict on purpose: `_Wire` ignores unknown keys, so when this model and the
    evaluator drifted apart the parse still succeeded and silently dropped the
    build and scope evidence instead of failing.
    """

    model_config = ConfigDict(extra="forbid")

    groups: dict[str, _Group]
    empty_patch: bool
    evaluator_record_ref: str
    preflight: dict[str, str | None] | None = None
    rejected_changes: tuple[dict[str, object], ...] = ()


class _Operating(_Wire):
    usage: dict[str, float | None] | None = None
    price: _Price | None = None
    source_references: tuple[str, ...]


class _Price(_Wire):
    amount: float
    currency: str
    basis: str


class _OperatingDetail(_Wire):
    coverage: Literal["measured", "estimated", "unavailable", "mixed", "uncertain"]


@dataclass(frozen=True)
class EvidenceReference:
    """Refs are content addressed; absent artifacts stay absent, never fabricated."""

    manifest_ref: str
    execution_ref: str | None
    patch_ref: str | None
    trace_ref: str | None
    raw_trajectory_ref: str | None = None

    def resolve(self, store: ObjectStore) -> tuple[bytes | None, bytes | None]:
        RunManifest.model_validate_json(store.read_bytes(self.manifest_ref))
        if self.execution_ref is not None:
            ExecutionOutcome.model_validate_json(store.read_bytes(self.execution_ref))
        patch = store.read_bytes(self.patch_ref) if self.patch_ref else None
        trace = store.read_bytes(self.trace_ref) if self.trace_ref else None
        if self.raw_trajectory_ref:
            store.read_bytes(self.raw_trajectory_ref)
        return patch, trace


@dataclass(frozen=True)
class AttemptRow:
    cell_id: str
    subject_id: str
    arm_id: str
    attempted: bool
    completed: bool
    passed: bool
    category: FailureCategory | None
    distinction: Literal["invalid_or_incomplete", "valid_but_wrong"] | None
    verdict: EvaluatorVerdict | None
    reference: EvidenceReference
    duration_seconds: float | None
    accounting: Accounting
    run_id: str = ""
    states: AttemptStates = AttemptStates()
    attempt_id: str = ""
    retry_of: str | None = None
    axes: OutcomeAxes = OutcomeAxes()
    annotations: tuple[DiagnosticAnnotation, ...] = ()
    terminal_cause: TerminalCause = "unknown"
    infrastructure_invalid: bool = False
    all_checks_passing: bool = False

    @property
    def primary_success(self) -> bool:
        return (
            self.states.completed_normally
            and self.states.evaluated
            and self.all_checks_passing
            and self.axes.scope == "clean"
        )

    @property
    def attempt_key(self) -> str:
        return f"{self.run_id}:{self.cell_id}" if self.run_id else self.cell_id


@dataclass(frozen=True)
class Denominators:
    attempted: int
    completed: int
    passed: int
    planned: int = 0
    dispatched: int = 0
    agent_started: int = 0
    completed_normally: int = 0
    evaluated: int = 0
    missing: int = 0


@dataclass(frozen=True)
class AttemptLedger:
    rows: tuple[AttemptRow, ...]

    def __post_init__(self) -> None:
        ids = [row.attempt_id for row in self.rows if row.attempt_id]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate attempt id")
        if any(row.retry_of == row.attempt_id for row in self.rows if row.retry_of):
            raise ValueError("retry cannot name itself")

    def _require_one_cohort(self) -> None:
        cohorts = {row.retry_of or "primary" for row in self.rows}
        if len(cohorts) > 1:
            raise ValueError("mixed retry cohorts; use cohorts() before counting")

    def counts(self) -> Denominators:
        self._require_one_cohort()
        return Denominators(
            attempted=sum(row.attempted for row in self.rows),
            completed=sum(row.completed for row in self.rows),
            passed=sum(row.passed for row in self.rows),
            planned=sum(row.states.planned for row in self.rows),
            dispatched=sum(row.states.dispatched for row in self.rows),
            agent_started=sum(row.states.agent_started for row in self.rows),
            completed_normally=sum(row.states.completed_normally for row in self.rows),
            evaluated=sum(row.states.evaluated for row in self.rows),
            missing=sum(row.states.missing for row in self.rows),
        )

    def rates(self) -> Rates:
        self._require_one_cohort()
        dispatched = [row for row in self.rows if row.states.dispatched]
        valid = [
            row for row in dispatched if row.states.evaluated and not row.infrastructure_invalid
        ]
        started = [row for row in valid if row.states.agent_started]
        completed = [row for row in valid if row.states.completed_normally]
        return Rates(
            _rate(sum(row.primary_success for row in dispatched), len(dispatched)),
            _rate(sum(row.primary_success for row in started), len(started)),
            _rate(
                sum(row.all_checks_passing for row in completed),
                len(completed),
            ),
            sum(row.infrastructure_invalid for row in dispatched),
            sum(not row.states.evaluated for row in dispatched),
        )

    def cohorts(self) -> dict[str, AttemptLedger]:
        cohorts: dict[str, list[AttemptRow]] = {"primary": []}
        for row in self.rows:
            key = "primary" if row.retry_of is None else f"retry:{row.retry_of}"
            cohorts.setdefault(key, []).append(row)
        return {key: AttemptLedger(tuple(rows)) for key, rows in cohorts.items()}


@dataclass(frozen=True)
class Rates:
    operational_yield: RateRecord
    primary_task_success: RateRecord
    conditional_correctness: RateRecord
    invalid: int
    unevaluable: int


def _rate(numerator: int, denominator: int) -> RateRecord:
    return RateRecord(numerator, denominator, numerator / denominator if denominator else None)


_NO_SUBMISSION_CAUSES = frozenset(
    {
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
    }
)
_ARTIFACT_REJECTIONS = frozenset(
    {
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
    }
)
_SCOPE_CAUSES = frozenset({"out_of_scope_edit", "tampering", "traversal", "escaping_symlink"})
_CORE_INFRASTRUCTURE_REASONS = frozenset({"bridge_exception", "exchange_mismatch"})


def terminal_cause(kind: TerminalKind, cause: str, detail: str = "") -> TerminalCause:
    """Preserve only distinctions supported by the shared cause or exact bridge detail."""
    if kind == "submitted":
        return "normal_submission"
    if kind == "evaluator_failure":
        return "evaluator_failure"
    if kind == "candidate_failure":
        if cause == "agent_deadline":
            return "wall_limit"
        if cause == "no_submission":
            prefix = "agent stopped without submitting: "
            suffix = detail.removeprefix(prefix)
            return (
                cast(TerminalCause, suffix)
                if detail.startswith(prefix) and suffix in _NO_SUBMISSION_CAUSES
                else "unknown"
            )
        if cause in _ARTIFACT_REJECTIONS or cause in _SCOPE_CAUSES:
            return cast(TerminalCause, cause)
        if cause in {"storage_exhausted", "memory_limit", "candidate_test_timeout", "nonzero_exit"}:
            return cast(TerminalCause, cause)
    if kind == "infrastructure_failure" and cause in {
        "container_start",
        "enforcement",
        "unexpected_exception",
        "harness_deadline",
        "cancelled",
        "mismatched_cell",
    }:
        return cast(TerminalCause, cause)
    return "unknown"


def _stop(outcome: ExecutionOutcome | None, store: ObjectStore) -> StopCause:
    if outcome is None:
        return NotStarted()
    if outcome.status == "succeeded":
        return Submitted()
    if outcome.trace_ref is None:
        return CoreStopped(outcome.error_type or "missing_trace")
    trace = _Trace.model_validate_json(store.read_bytes(outcome.trace_ref))
    bridge = trace.bridge_outcome
    if bridge is None:
        return CoreStopped(outcome.error_type or "unknown")
    try:
        if bridge.kind == "candidate_failure":
            return CandidateStopped(TypeAdapter(CandidateCause).validate_python(bridge.cause))
        return InfrastructureStopped(TypeAdapter(InfrastructureCause).validate_python(bridge.cause))
    except ValidationError:
        return CoreStopped("unknown_bridge_cause")


def _infrastructure_invalid(stop: StopCause, trace: _Trace | None) -> bool:
    return isinstance(stop, InfrastructureStopped) or (
        isinstance(stop, CoreStopped)
        and trace is not None
        and trace.bridge_outcome is None
        and trace.rejection_reason in _CORE_INFRASTRUCTURE_REASONS
    )


def _verdict(cell_id: str, manifest: RunManifest, store: ObjectStore) -> EvaluatorVerdict | None:
    detail, record = _evaluation_detail(cell_id, manifest, store)
    if detail is None or record is None:
        return None
    preflight = detail.preflight
    from assay.investigations.workflow_correctness import PreflightResult

    return EvaluatorVerdict(
        record.verdict.value,
        tuple(
            GroupVerdict(group.status, group.cause, name)
            for name, group in sorted(detail.groups.items())
        ),
        record.verdict.reason_codes[0] if record.verdict.reason_codes else None,
        PreflightResult(
            cast(Literal["passed", "failed", "unavailable"], preflight["status"]),
            preflight.get("cause"),
        )
        if preflight is not None and preflight.get("status") in {"passed", "failed", "unavailable"}
        else None,
    )


def _evaluation_detail(
    cell_id: str,
    manifest: RunManifest,
    store: ObjectStore,
) -> tuple[_Detail | None, _Evidence | None]:
    refs = [
        ref for key, ref in manifest.evaluation_records.items() if key.startswith(f"{cell_id}:")
    ]
    if len(refs) > 1:
        raise ValueError(f"multiple evaluator records for {cell_id}")
    if not refs:
        return None, None
    raw = store.read_bytes(refs[0])
    if _EvidenceMarker.model_validate_json(raw).record_schema != "paa-evidence-record/0.3.0-draft":
        return None, None
    record = _Evidence.model_validate_json(raw)
    if len(record.payload.detail_refs) != 1:
        raise ValueError(f"missing per-group evaluator detail for {cell_id}")
    return _Detail.model_validate_json(store.read_bytes(record.payload.detail_refs[0])), record


def _agent_started(ref: str | None, store: ObjectStore) -> bool:
    if ref is None:
        return False
    raw = store.read_bytes(ref)
    if b'"assay-pier-raw-artifact/0.1.0"' in raw:
        from code_extension.metrics import artifact_bytes

        raw = artifact_bytes(store, ref)
    trajectory = json.loads(raw)
    return any(event.get("kind") == "model_request" for event in trajectory.get("events", []))


def _axes(
    verdict: EvaluatorVerdict | None,
    detail: _Detail | None,
    stop: StopCause,
    terminal: TerminalCause,
) -> OutcomeAxes:
    groups = {group.name: group for group in verdict.groups} if verdict else {}

    def status(name: str) -> Literal["passed", "failed", "unavailable"]:
        return groups[name].status if name in groups else "unavailable"

    feature = status("new_behavior")
    regression_parts = (status("visible_regression"), status("hidden_regression"))
    regression: Literal["passed", "failed", "unavailable"] = (
        "failed"
        if "failed" in regression_parts
        else "passed"
        if all(part == "passed" for part in regression_parts)
        else "unavailable"
    )
    preflight = detail.preflight if detail else None
    if preflight and preflight.get("status") in {"passed", "failed", "unavailable"}:
        build = cast(Literal["passed", "failed", "unavailable"], preflight["status"])
    elif any(
        group.cause and group.cause.startswith(("typecheck_", "build_"))
        for group in groups.values()
    ):
        build = "failed"
    else:
        build = "unavailable"
    scope: Literal["clean", "violated", "unknown"] = (
        "violated"
        if (
            isinstance(stop, CandidateStopped)
            and stop.cause in _SCOPE_CAUSES
            or detail is not None
            and bool(detail.rejected_changes)
        )
        else "clean"
        if isinstance(stop, Submitted | CandidateStopped)
        else "unknown"
    )
    return OutcomeAxes(build, feature, regression, scope, terminal)


def _accounting(cell_id: str, manifest: RunManifest, store: ObjectStore) -> Accounting:
    ref = manifest.operating_records.get(f"worker:{cell_id}")
    if ref is None:
        return Accounting()
    record = _Operating.model_validate_json(store.read_bytes(ref))
    if len(record.source_references) < 2:
        raise ValueError(f"missing operating coverage for {cell_id}")
    detail = _OperatingDetail.model_validate_json(store.read_bytes(record.source_references[1]))
    price = record.price
    return Accounting(
        usage=record.usage,
        amount=price.amount if price else None,
        currency=price.currency if price else None,
        basis=price.basis if price else None,
        coverage=detail.coverage,
    )


def build_ledger(
    *,
    plan: ExecutionPlanV3,
    manifest_ref: str,
    store: ObjectStore,
    judgments: Mapping[str, OperatorCategory],
    annotations: Mapping[str, tuple[DiagnosticAnnotation, ...]] | None = None,
    retry_of: Mapping[str, str] | None = None,
) -> AttemptLedger:
    """Read dispatch records; reject missing/extra judgments and inconsistent evidence."""
    manifest = RunManifest.model_validate_json(store.read_bytes(manifest_ref))
    if manifest.plan_ref != digest_bytes(canonical_json(plan.model_dump(mode="json"))):
        raise ValueError("run manifest belongs to another plan")
    expected = {cell.id for cell in plan.cells}
    if len(expected) != len(plan.cells) or not set(manifest.execution_records) <= expected:
        raise ValueError("execution records do not match planned attempts")
    if not set(judgments) <= expected:
        raise ValueError("judgment names an unknown attempt")
    annotations = annotations or {}
    retry_of = retry_of or {}
    if not set(annotations) <= expected or not set(retry_of) <= expected:
        raise ValueError("annotation or retry names an unknown attempt")
    if set(manifest.missing_coordinates) & set(manifest.execution_records):
        raise ValueError("missing coordinate has an execution record")
    rows: list[AttemptRow] = []
    used_judgments: set[str] = set()
    for cell in plan.cells:
        execution_ref = manifest.execution_records.get(cell.id)
        outcome = (
            ExecutionOutcome.model_validate_json(store.read_bytes(execution_ref))
            if execution_ref is not None
            else None
        )
        if outcome is not None and outcome.coordinate != cell:
            raise ValueError(f"execution record belongs to another coordinate: {cell.id}")
        output = (
            _Output.model_validate_json(store.read_bytes(outcome.output_ref))
            if outcome is not None and outcome.output_ref is not None
            else None
        )
        trace_ref = outcome.trace_ref if outcome is not None else manifest.interruption_ref
        trace = _Trace.model_validate_json(store.read_bytes(trace_ref)) if trace_ref else None
        artifact_refs = trace.artifact_refs if trace is not None else {}
        ref = EvidenceReference(
            manifest_ref,
            execution_ref,
            output.patch_ref
            if output
            else artifact_refs.get("stopped/candidate.patch")
            or artifact_refs.get("candidate.patch"),
            trace_ref,
            output.raw_trajectory_ref
            if output
            else artifact_refs.get("trajectory.json")
            or artifact_refs.get("stopped/trajectory.json"),
        )
        ref.resolve(store)
        verdict = _verdict(cell.id, manifest, store)
        detail, _ = _evaluation_detail(cell.id, manifest, store)
        stop = _stop(outcome, store)
        classification = classify(stop, verdict)
        bridge = trace.bridge_outcome if trace else None
        terminal = (
            terminal_cause("submitted", "")
            if outcome is not None and outcome.status == "succeeded"
            else terminal_cause(bridge.kind, bridge.cause, bridge.detail)
            if bridge
            else "unknown"
        )
        category: FailureCategory | None
        distinction: Literal["invalid_or_incomplete", "valid_but_wrong"] | None = None
        if (
            isinstance(stop, CoreStopped)
            and stop.error_type == "unknown_bridge_cause"
            or isinstance(classification, Passed)
        ):
            category = None
        elif isinstance(classification, NeedsOperatorJudgment):
            distinction = classification.distinction
            category = judgments.get(cell.id)
            if category is None:
                raise ValueError(f"operator judgment required for {cell.id}")
            if trace_ref is None or category.trace_digest != trace_ref:
                raise ValueError(f"operator judgment has wrong trace for {cell.id}")
            used_judgments.add(cell.id)
        else:
            category = classification
        if isinstance(category, HarnessOrProviderFailure | Timeout) and cell.id in judgments:
            raise ValueError(f"mechanical category cannot be overridden: {cell.id}")
        if isinstance(classification, Passed) and cell.id in judgments:
            raise ValueError(f"passed attempt cannot have a failure judgment: {cell.id}")
        duration = None
        if outcome is not None:
            start = datetime.fromisoformat(outcome.started_at.replace("Z", "+00:00"))
            end = datetime.fromisoformat(outcome.completed_at.replace("Z", "+00:00"))
            duration = (end - start).total_seconds()
        valid_evaluation = verdict is not None and verdict.value != "unavailable"
        states = AttemptStates(
            planned=True,
            dispatched=outcome is not None,
            agent_started=_agent_started(ref.raw_trajectory_ref, store),
            completed_normally=outcome is not None and outcome.status == "succeeded",
            evaluated=valid_evaluation,
            passed=isinstance(classification, Passed),
            missing=cell.id in manifest.missing_coordinates,
        )
        axes = _axes(verdict, detail, stop, terminal)
        groups = {group.name: group.status for group in verdict.groups} if verdict else {}
        all_checks_passing = valid_evaluation and all(
            groups.get(name) == "passed"
            for name in ("visible_regression", "hidden_regression", "new_behavior")
        )
        for annotation in annotations.get(cell.id, ()):
            check_refs = (
                value
                for key, value in manifest.evaluation_records.items()
                if key.startswith(f"{cell.id}:")
            )
            valid_refs = {value for value in (trace_ref, *check_refs) if value}
            if annotation.evidence_ref not in valid_refs:
                raise ValueError(f"annotation has wrong trace or check for {cell.id}")
        rows.append(
            AttemptRow(
                cell.id,
                cell.subject_id,
                cell.arm_id,
                True,
                outcome is not None and outcome.status == "succeeded",
                isinstance(classification, Passed),
                category,
                distinction,
                verdict,
                ref,
                duration,
                _accounting(cell.id, manifest, store),
                manifest.run_id,
                states,
                f"{manifest.run_id}:{cell.id}",
                retry_of.get(cell.id),
                axes,
                annotations.get(cell.id, ()),
                terminal,
                _infrastructure_invalid(stop, trace),
                all_checks_passing,
            )
        )
    if set(judgments) != used_judgments:
        raise ValueError("unused operator judgments")
    return AttemptLedger(tuple(rows))
