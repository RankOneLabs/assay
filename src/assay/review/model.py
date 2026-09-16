"""Shared JSON-native view models for the review server and exporter."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from typing import Literal

from assay.canonical import CanonicalizationError, canonical_json

type JSONValue = None | bool | int | float | str | list[JSONValue] | JSONObject
type JSONObject = dict[str, JSONValue]

type RunStatus = Literal["complete", "incomplete", "unmanifested"]
type CellStatus = Literal["succeeded", "failed", "missing", "excluded", "invalid", "conflicted"]
type EvaluationStatus = Literal["succeeded", "failed", "missing", "invalid", "conflicted"]
type ReportMetric = Literal["scalar", "ordinal", "classification"]
type CostCoverage = Literal["measured", "estimated", "unavailable", "mixed"]
type PreviewKind = Literal["json", "text", "binary", "unavailable"]
type InputKind = Literal["consistency", "generic", "unavailable"]
type ComparisonKind = Literal["numeric", "ordinal", "classification", "unknown"]
type RecomputeStatus = Literal["matched", "mismatched", "unsupported", "failed"]
type VerificationScope = Literal["root", "bundle"]
type VerificationStatus = Literal["passed", "failed", "partial"]


def to_json_value(value: object) -> JSONValue:
    """Recursively project a view dataclass into JSON-native values."""
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: to_json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, (list, tuple)):
        return [to_json_value(item) for item in value]
    if isinstance(value, dict):
        result: JSONObject = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError("view model dictionaries must have string keys")
            result[key] = to_json_value(item)
        return result
    raise CanonicalizationError(f"unsupported view model value: {type(value).__name__}")


def canonical_view_json(value: object) -> bytes:
    """Encode a view with Assay's canonical JSON profile."""
    return canonical_json(to_json_value(value))


@dataclass(frozen=True, slots=True)
class StoreSummary:
    root: str | None
    runs: tuple[RunSummary, ...]
    reports: tuple[ReportSummary, ...]
    issues: tuple[ReadIssue, ...]


@dataclass(frozen=True, slots=True)
class RunSummary:
    run_key: str
    run_id: str
    manifest_ref: str | None
    plan_ref: str
    snapshot_ref: str | None
    status: RunStatus
    subjects: int | None
    arms: tuple[str, ...] | None
    worker_repeats: int | None
    concurrency: int | None
    jig_revision: str | None
    runtime_id: str | None
    runtime_version: str | None
    assay_version: str | None
    started_at: str | None
    completed_at: str | None
    cells_total: int | None
    cells_succeeded: int
    cells_failed: int
    cells_missing: int | None
    cells_invalid: int
    cells_conflicted: int
    evaluations_total: int | None
    evaluations_succeeded: int
    evaluations_failed: int
    evaluations_missing: int | None
    evaluations_invalid: int
    evaluations_conflicted: int
    exclusions: tuple[ExclusionView, ...]
    cost: CostView
    issues: tuple[ReadIssue, ...]


@dataclass(frozen=True, slots=True)
class RunDetail:
    summary: RunSummary
    subjects: tuple[SubjectView, ...]
    arms: tuple[ArmView, ...]
    evaluators: tuple[EvaluatorView, ...]
    cells: tuple[CellSummary, ...]
    missing_coordinates: tuple[str, ...] | None
    cost_estimate: PlannedCostView | None


@dataclass(frozen=True, slots=True)
class CellSummary:
    cell_id: str
    subject_id: str
    arm_id: str
    worker_repeat: int
    status: CellStatus
    error_type: str | None
    error_message: str | None
    record_refs: tuple[str, ...]
    exclusion: ExclusionView | None
    verdicts: tuple[VerdictSummary, ...]
    issues: tuple[ReadIssue, ...]


@dataclass(frozen=True, slots=True)
class VerdictSummary:
    evaluator_id: str
    values: tuple[str | int | float | None, ...]
    repeat_statuses: tuple[EvaluationStatus, ...]
    failures: tuple[str, ...]
    agreed: bool | None
    categories: tuple[str, ...] | None


@dataclass(frozen=True, slots=True)
class CellDetail:
    summary: CellSummary
    input_ref: str | None
    input_preview: InputView
    output_ref: str | None
    output_text: str | None
    output_preview: ObjectPreview | None
    trace_ref: str | None
    trace_preview: ObjectPreview | None
    recorded_prompt: str | None
    recorded_prompt_ref: str | None
    evaluations: tuple[EvaluationView, ...]
    started_at: str | None
    completed_at: str | None


@dataclass(frozen=True, slots=True)
class EvaluationView:
    run_key: str
    cell_id: str
    coordinate_id: str
    evaluator_id: str
    evaluator_repeat: int
    status: EvaluationStatus
    record_refs: tuple[str, ...]
    verdict: str | int | float | None
    reason_codes: tuple[str, ...]
    error_type: str | None
    error_message: str | None
    detail_refs: tuple[str, ...]
    detail: JSONValue
    issues: tuple[ReadIssue, ...]


@dataclass(frozen=True, slots=True)
class PairView:
    run_key: str
    subject_id: str
    subject_label: str | None
    reference_arm: str
    candidate_arm: str
    reference_cells: tuple[CellDetail, ...]
    candidate_cells: tuple[CellDetail, ...]
    treatment_diff: DiffView
    output_diffs: tuple[DiffView, ...]
    issues: tuple[ReadIssue, ...]


@dataclass(frozen=True, slots=True)
class ReportSummary:
    report_ref: str
    config_ref: str
    metric: ReportMetric
    evaluator_id: str
    reference_arm: str | None
    candidates: tuple[str, ...] | None
    engine_version: str | None
    recomputable: bool
    recompute_disabled_reason: str | None
    manifest_refs: tuple[str, ...]
    issues: tuple[ReadIssue, ...]


@dataclass(frozen=True, slots=True)
class ReportDetail:
    summary: ReportSummary
    report: JSONObject
    comparisons: tuple[ComparisonView, ...]
    missingness: JSONObject
    exclusions: tuple[ExclusionView, ...]
    costs: CostView
    subject_labels: dict[str, str]


@dataclass(frozen=True, slots=True)
class CostView:
    coverage: CostCoverage
    coverage_counts: dict[str, int]
    amounts: dict[str, float]
    by_stage_arm: JSONObject
    attempts: int
    expected_attempts: int | None
    unaccounted_attempts: int | None
    partial: bool
    issues: tuple[ReadIssue, ...]


@dataclass(frozen=True, slots=True)
class PlannedCostView:
    amount: float | None
    currency: str | None
    coverage: CostCoverage


@dataclass(frozen=True, slots=True)
class ReadIssue:
    code: str
    message: str
    ref: str | None
    coordinate_id: str | None


@dataclass(frozen=True, slots=True)
class SubjectView:
    id: str
    label: str
    digest: str
    partition: str


@dataclass(frozen=True, slots=True)
class ArmView:
    id: str
    worker_id: str
    worker_version: str
    intervention_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvaluatorView:
    id: str
    identity: JSONObject
    repeats: int
    categories: tuple[str, ...] | None


@dataclass(frozen=True, slots=True)
class ExclusionView:
    subject_id: str
    arm_id: str
    classification: str
    reason: str
    manifest_ref: str | None


@dataclass(frozen=True, slots=True)
class ObjectPreview:
    ref: str
    kind: PreviewKind
    text: str | None
    size_bytes: int | None
    truncated: bool
    issues: tuple[ReadIssue, ...]


@dataclass(frozen=True, slots=True)
class InputView:
    kind: InputKind
    instruction: str | None
    files: dict[str, str] | None
    artifact: ObjectPreview | None


@dataclass(frozen=True, slots=True)
class DiffView:
    left_ref: str | None
    right_ref: str | None
    left_text: str | None
    right_text: str | None
    unified: str | None
    unavailable_reason: str | None


@dataclass(frozen=True, slots=True)
class ComparisonView:
    kind: ComparisonKind
    reference: str
    candidate: str
    values: JSONObject


@dataclass(frozen=True, slots=True)
class RecomputeResult:
    status: RecomputeStatus
    matched: bool | None
    stored_digest: str
    recomputed_digest: str | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class VerificationResult:
    scope: VerificationScope
    root_ref: str
    status: VerificationStatus
    checks: tuple[str, ...]
    failures: tuple[VerificationFailure, ...]
    unsupported_reason: str | None


@dataclass(frozen=True, slots=True)
class VerificationFailure:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ExportData:
    schema_version: Literal["assay-review-export/0.1.0"]
    root_ref: str
    store: StoreSummary
    views: dict[str, JSONValue]
    objects: dict[str, EmbeddedObject]
    capabilities: dict[str, bool]


@dataclass(frozen=True, slots=True)
class EmbeddedObject:
    preview: ObjectPreview
    download_base64: str | None
    download_unavailable_reason: str | None
