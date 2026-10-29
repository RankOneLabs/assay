"""One inspectable row for each planned extension attempt, including unsettled cells."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, TypeAdapter

from assay.canonical import canonical_json, digest_bytes
from assay.execution import Accounting
from assay.models import ExecutionOutcome, ExecutionPlanV3, RunManifest
from assay.pier_protocol import CandidateCause, InfrastructureCause
from assay.store import ObjectStore
from code_extension.classification import (
    CandidateStopped,
    CoreStopped,
    EvaluatorVerdict,
    FailureCategory,
    GroupVerdict,
    HarnessOrProviderFailure,
    InfrastructureStopped,
    NeedsOperatorJudgment,
    NotStarted,
    OperatorCategory,
    Passed,
    StopCause,
    Submitted,
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
    cause: CandidateCause | InfrastructureCause


class _Trace(_Wire):
    bridge_outcome: _BridgeOutcome | None = None
    artifact_refs: dict[str, str] = {}


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
    groups: dict[str, _Group]


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

    @property
    def attempt_key(self) -> str:
        return f"{self.run_id}:{self.cell_id}" if self.run_id else self.cell_id


@dataclass(frozen=True)
class Denominators:
    attempted: int
    completed: int
    passed: int


@dataclass(frozen=True)
class AttemptLedger:
    rows: tuple[AttemptRow, ...]

    def counts(self) -> Denominators:
        return Denominators(
            attempted=sum(row.attempted for row in self.rows),
            completed=sum(row.completed for row in self.rows),
            passed=sum(row.passed for row in self.rows),
        )


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
    if bridge.kind == "candidate_failure":
        return CandidateStopped(TypeAdapter(CandidateCause).validate_python(bridge.cause))
    return InfrastructureStopped(TypeAdapter(InfrastructureCause).validate_python(bridge.cause))


def _verdict(cell_id: str, manifest: RunManifest, store: ObjectStore) -> EvaluatorVerdict | None:
    refs = [
        ref for key, ref in manifest.evaluation_records.items()
        if key.startswith(f"{cell_id}:")
    ]
    if len(refs) > 1:
        raise ValueError(f"multiple evaluator records for {cell_id}")
    if not refs:
        return None
    raw = store.read_bytes(refs[0])
    if _EvidenceMarker.model_validate_json(raw).record_schema != "paa-evidence-record/0.3.0-draft":
        return None
    record = _Evidence.model_validate_json(raw)
    if len(record.payload.detail_refs) != 1:
        raise ValueError(f"missing per-group evaluator detail for {cell_id}")
    detail = _Detail.model_validate_json(store.read_bytes(record.payload.detail_refs[0]))
    return EvaluatorVerdict(
        record.verdict.value,
        tuple(
            GroupVerdict(group.status, group.cause)
            for _, group in sorted(detail.groups.items())
        ),
        record.verdict.reason_codes[0] if record.verdict.reason_codes else None,
    )


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
    *, plan: ExecutionPlanV3, manifest_ref: str, store: ObjectStore,
    judgments: Mapping[str, OperatorCategory],
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
    rows: list[AttemptRow] = []
    used_judgments: set[str] = set()
    for cell in plan.cells:
        execution_ref = manifest.execution_records.get(cell.id)
        outcome = (
            ExecutionOutcome.model_validate_json(store.read_bytes(execution_ref))
            if execution_ref is not None else None
        )
        if outcome is not None and outcome.coordinate != cell:
            raise ValueError(f"execution record belongs to another coordinate: {cell.id}")
        output = (
            _Output.model_validate_json(store.read_bytes(outcome.output_ref))
            if outcome is not None and outcome.output_ref is not None else None
        )
        trace_ref = outcome.trace_ref if outcome is not None else manifest.interruption_ref
        trace = _Trace.model_validate_json(store.read_bytes(trace_ref)) if trace_ref else None
        artifact_refs = trace.artifact_refs if trace is not None else {}
        ref = EvidenceReference(
            manifest_ref, execution_ref,
            output.patch_ref if output else artifact_refs.get("stopped/candidate.patch")
            or artifact_refs.get("candidate.patch"),
            trace_ref,
            output.raw_trajectory_ref if output else artifact_refs.get("trajectory.json")
            or artifact_refs.get("stopped/trajectory.json"),
        )
        ref.resolve(store)
        verdict = _verdict(cell.id, manifest, store)
        classification = classify(_stop(outcome, store), verdict)
        category: FailureCategory | None
        distinction: Literal["invalid_or_incomplete", "valid_but_wrong"] | None = None
        if isinstance(classification, Passed):
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
        if isinstance(classification, HarnessOrProviderFailure | Timeout) and cell.id in judgments:
            raise ValueError(f"mechanical category cannot be overridden: {cell.id}")
        if isinstance(classification, Passed) and cell.id in judgments:
            raise ValueError(f"passed attempt cannot have a failure judgment: {cell.id}")
        duration = None
        if outcome is not None:
            start = datetime.fromisoformat(outcome.started_at.replace("Z", "+00:00"))
            end = datetime.fromisoformat(outcome.completed_at.replace("Z", "+00:00"))
            duration = (end - start).total_seconds()
        rows.append(AttemptRow(
            cell.id, cell.subject_id, cell.arm_id,
            True, outcome is not None and outcome.status == "succeeded",
            isinstance(classification, Passed), category, distinction, verdict, ref,
            duration, _accounting(cell.id, manifest, store), manifest.run_id,
        ))
    if set(judgments) != used_judgments:
        raise ValueError("unused operator judgments")
    return AttemptLedger(tuple(rows))
