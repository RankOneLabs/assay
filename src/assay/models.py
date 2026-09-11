"""Closed wire models for snapshots, plans, outcomes, and manifests."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    WithJsonSchema,
    field_validator,
    model_validator,
)

from assay.immutable import freeze
from assay.statistical_limits import MAX_BOOTSTRAP_SAMPLES

Sha256Ref = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
NonEmpty = Annotated[str, StringConstraints(min_length=1)]


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    @model_validator(mode="after")
    def freeze_payloads(self) -> Self:
        return self._freeze_payloads()

    def _freeze_payloads(self) -> Self:
        for name in type(self).model_fields:
            object.__setattr__(self, name, freeze(getattr(self, name)))
        return self

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> Self:
        # Preserve Pydantic's unvalidated-copy semantics, but never introduce
        # mutable JSON containers through a copy's updates.
        return super().model_copy(update=update, deep=deep)._freeze_payloads()


class Subject(WireModel):
    id: Identifier
    label: NonEmpty
    digest: Sha256Ref
    partition: Identifier
    payload_ref: Sha256Ref


class Arm(WireModel):
    id: Identifier
    worker: Annotated[
        dict[str, Any],
        WithJsonSchema(
            {
                "type": "object",
                "required": ["id", "version"],
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "version": {"type": "string", "minLength": 1},
                },
                "additionalProperties": True,
            }
        ),
    ]
    intervention: dict[str, Any]
    conditions: dict[str, Any] = Field(default_factory=dict)

    @field_validator("worker")
    @classmethod
    def worker_identity(cls, value: dict[str, Any]) -> dict[str, Any]:
        if any(not isinstance(value.get(key), str) or not value[key] for key in ("id", "version")):
            raise ValueError("worker requires nonempty id and version")
        return value


class Realization(WireModel):
    subject_id: Identifier
    arm_id: Identifier
    digest: Sha256Ref
    artifact_ref: Sha256Ref


class EvaluationBasis(WireModel):
    kind: Literal["invariant", "reference_label", "rubric", "human_gold", "downstream_result"]
    ref: NonEmpty


class EvaluatorIdentity(WireModel):
    property: NonEmpty
    target: Literal["input", "process", "output", "outcome"]
    technique: Literal["deterministic", "classifier", "llm_judge", "human"]
    evaluation_basis: EvaluationBasis
    epistemic_status: Literal["proxy", "ground_truth"]
    version: NonEmpty
    authority: Literal["advisory", "blocking"]


_identity_schema = EvaluatorIdentity.model_json_schema()
_identity_schema["properties"]["evaluation_basis"] = EvaluationBasis.model_json_schema()
_identity_schema.pop("$defs", None)


class EvaluatorDeclaration(WireModel):
    id: Identifier
    identity: Annotated[dict[str, Any], WithJsonSchema(_identity_schema)]
    payload_schema: NonEmpty
    payload_schema_ref: Sha256Ref
    basis_ref: Sha256Ref
    configuration: dict[str, Any] = Field(default_factory=dict)
    repeats: int = Field(ge=1)

    @field_validator("identity")
    @classmethod
    def valid_identity(cls, value: dict[str, Any]) -> dict[str, Any]:
        return EvaluatorIdentity.model_validate(value).model_dump(mode="json")


class PriceEstimate(WireModel):
    amount: float | None = Field(ge=0)
    currency: str | None = None
    coverage: Literal["measured", "estimated", "unavailable", "mixed"]

    @model_validator(mode="after")
    def price_coverage(self) -> PriceEstimate:
        if self.amount is not None and (not self.currency or self.coverage == "unavailable"):
            raise ValueError("available price requires currency and available coverage")
        if self.amount is None and self.coverage in ("measured", "estimated"):
            raise ValueError("measured or estimated coverage requires an amount")
        return self


class StudySnapshot(WireModel):
    schema_version: Literal["assay-study-snapshot/0.1.0"] = "assay-study-snapshot/0.1.0"
    subjects: tuple[Subject, ...] = Field(min_length=1)
    arms: tuple[Arm, ...] = Field(min_length=1)
    realizations: tuple[Realization, ...]
    evaluators: tuple[EvaluatorDeclaration, ...] = Field(min_length=1)
    paa_task_ref: Sha256Ref
    paa_scope: NonEmpty | None = None
    task_schema_ref: Sha256Ref
    evidence_schema_ref: Sha256Ref
    operating_schema_ref: Sha256Ref
    pricing_catalog_ref: Sha256Ref
    pricing_assumptions: dict[str, Any] = Field(default_factory=dict)

    @field_validator("subjects", "arms", "evaluators")
    @classmethod
    def sort_declarations(cls, value: tuple[Any, ...]) -> tuple[Any, ...]:
        return tuple(sorted(value, key=lambda item: item.id))

    @field_validator("realizations")
    @classmethod
    def sort_realizations(cls, value: tuple[Realization, ...]) -> tuple[Realization, ...]:
        return tuple(sorted(value, key=lambda item: (item.subject_id, item.arm_id)))

    @model_validator(mode="after")
    def consistent_grid(self) -> StudySnapshot:
        subject_ids = [value.id for value in self.subjects]
        arm_ids = [value.id for value in self.arms]
        evaluator_ids = [value.id for value in self.evaluators]
        if len(subject_ids) != len(set(subject_ids)) or len(
            {s.label for s in self.subjects}
        ) != len(self.subjects):
            raise ValueError("subject ids and labels must be unique")
        if len({subject.digest for subject in self.subjects}) != len(self.subjects):
            raise ValueError(
                "subject digests must be unique; duplicates are not independent subjects"
            )
        if len(arm_ids) != len(set(arm_ids)) or len(evaluator_ids) != len(set(evaluator_ids)):
            raise ValueError("arm and evaluator ids must be unique")
        actual = {(value.subject_id, value.arm_id) for value in self.realizations}
        expected = {(subject, arm) for subject in subject_ids for arm in arm_ids}
        if len(actual) != len(self.realizations) or actual != expected:
            raise ValueError("realizations must cover the subject/arm grid exactly once")
        return self


class Exclusion(WireModel):
    subject_id: Identifier
    arm_id: Identifier
    classification: NonEmpty
    reason: NonEmpty


class CellCoordinate(WireModel):
    subject_id: Identifier
    arm_id: Identifier
    worker_repeat: int = Field(ge=0, strict=True)
    realization_ref: Sha256Ref

    @property
    def id(self) -> str:
        return f"{self.subject_id}:{self.arm_id}:w{self.worker_repeat}"


class EvaluationCoordinate(WireModel):
    cell_id: Annotated[
        str,
        StringConstraints(
            pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*:[A-Za-z0-9][A-Za-z0-9_.-]*:w[0-9]+$"
        ),
    ]
    evaluator_id: Identifier
    evaluator_repeat: int = Field(ge=0, strict=True)

    @property
    def id(self) -> str:
        return f"{self.cell_id}:{self.evaluator_id}:e{self.evaluator_repeat}"


class ExecutionPlan(WireModel):
    schema_version: Literal["assay-execution-plan/0.1.0"] = "assay-execution-plan/0.1.0"
    snapshot_ref: Sha256Ref
    preparation_mode: Literal["none", "authorized"] = "none"
    worker_repeats: int = Field(ge=1)
    concurrency: int = Field(default=4, ge=1, strict=True)
    exclusions: tuple[Exclusion, ...] = ()
    cells: tuple[CellCoordinate, ...]
    evaluations: tuple[EvaluationCoordinate, ...]
    declaration_hashes: tuple[Sha256Ref, ...]
    execution_conditions_ref: Sha256Ref
    cost_estimate: PriceEstimate
    arm_cost_estimates: dict[Identifier, PriceEstimate]
    jig_revision: str
    assay_version: str

    @model_validator(mode="after")
    def unique_coordinates(self) -> ExecutionPlan:
        cells = {cell.id for cell in self.cells}
        evaluations = {item.id for item in self.evaluations}
        if len(cells) != len(self.cells) or len(evaluations) != len(self.evaluations):
            raise ValueError("duplicate plan coordinates")
        if any(item.cell_id not in cells for item in self.evaluations):
            raise ValueError("evaluation references unknown cell")
        if any(cell.worker_repeat >= self.worker_repeats for cell in self.cells):
            raise ValueError("worker repeat exceeds declared count")
        return self


class RunRecord(WireModel):
    run_id: Identifier
    plan_ref: Sha256Ref
    started_at: str
    completed_at: str

    @model_validator(mode="after")
    def ordered_timestamps(self) -> RunRecord:
        start = datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(self.completed_at.replace("Z", "+00:00"))
        if start.utcoffset() is None or end.utcoffset() is None or end < start:
            raise ValueError("timestamps must be timezone-aware and ordered")
        return self


class ExecutionOutcome(RunRecord):
    schema_version: Literal["assay-execution-outcome/0.1.0"] = "assay-execution-outcome/0.1.0"
    coordinate: CellCoordinate
    status: Literal["succeeded", "failed"]
    input_ref: Sha256Ref
    output_ref: Sha256Ref | None = None
    trace_ref: Sha256Ref | None = None
    error_type: str | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def consistent_status(self) -> ExecutionOutcome:
        if self.status == "succeeded":
            if (
                self.output_ref is None
                or self.error_type is not None
                or self.error_message is not None
            ):
                raise ValueError("successful execution needs output and no error")
        elif self.output_ref is not None or not self.error_type or self.error_message is None:
            raise ValueError("failed execution needs an error and no output")
        if self.input_ref != self.coordinate.realization_ref:
            raise ValueError("execution input must match planned realization")
        return self


class EvaluationFailure(RunRecord):
    schema_version: Literal["assay-evaluation-failure/0.1.0"] = "assay-evaluation-failure/0.1.0"
    coordinate: EvaluationCoordinate
    error_type: str
    error_message: str
    trace_ref: Sha256Ref | None = None


class RunManifest(WireModel):
    schema_version: Literal["assay-run-manifest/0.1.0"] = "assay-run-manifest/0.1.0"
    run_id: Identifier
    plan_ref: Sha256Ref
    status: Literal["complete", "incomplete"]
    execution_records: dict[str, Sha256Ref]
    evaluation_records: dict[str, Sha256Ref]
    operating_records: dict[str, Sha256Ref] = Field(default_factory=dict)
    missing_coordinates: tuple[str, ...]

    @model_validator(mode="after")
    def unique_addresses(self) -> RunManifest:
        refs = [
            *self.execution_records.values(),
            *self.evaluation_records.values(),
            *self.operating_records.values(),
        ]
        if len(refs) != len(set(refs)):
            raise ValueError("terminal and operating records must have unique addresses")
        if len(self.missing_coordinates) != len(set(self.missing_coordinates)):
            raise ValueError("missing coordinates must be unique")
        return self


class StatisticalProfile(WireModel):
    name: Literal["paired-v2"] = "paired-v2"
    seed: int = Field(ge=0, strict=True)
    bootstrap_samples: int = Field(ge=100, le=MAX_BOOTSTRAP_SAMPLES, strict=True)
    alpha: float = Field(default=0.05, ge=0.05, le=0.05)
    min_subjects: Literal[10] = 10


class ReportConfig(WireModel):
    schema_version: Literal["assay-report-config/0.1.0"] = "assay-report-config/0.1.0"
    manifest_refs: tuple[Sha256Ref, ...] = Field(min_length=1)
    record_refs: tuple[Sha256Ref, ...]
    reference_arm: Identifier
    candidates: tuple[Identifier, ...] = Field(min_length=1)
    evaluator_id: Identifier
    metric: Literal["scalar", "ordinal", "classification"]
    scalar_direction: Literal["higher_is_better", "lower_is_better"] | None = None
    evaluator_repeat_aggregation: Literal["mean", "median", "majority"]
    worker_repeat_aggregation: Literal["mean", "median", "majority"]
    ordinal_mapping: dict[str, float] | None = None
    categories: tuple[NonEmpty, ...] = ()
    positive_label: str | None = None
    label_key: NonEmpty = "label"
    statistical_profile: StatisticalProfile
    engine_version: str

    @model_validator(mode="after")
    def valid_report(self) -> ReportConfig:
        if self.metric == "scalar" or self.ordinal_mapping is not None:
            if self.scalar_direction is None:
                raise ValueError("numeric reports require explicit scalar_direction")
        elif self.scalar_direction is not None:
            raise ValueError("scalar_direction is only valid for numeric reports")
        aggregations = {self.evaluator_repeat_aggregation, self.worker_repeat_aggregation}
        if self.ordinal_mapping is not None and self.metric != "ordinal":
            raise ValueError("numeric mappings are only valid for ordinal metrics")
        allowed = {"mean", "median"}
        if self.metric == "classification":
            allowed = {"majority"}
        elif self.metric == "ordinal" and self.ordinal_mapping is None:
            allowed = {"median", "majority"}
        if not aggregations <= allowed:
            raise ValueError("aggregation is incompatible with the metric")
        if self.reference_arm in self.candidates or len(set(self.candidates)) != len(
            self.candidates
        ):
            raise ValueError("candidates must be unique and exclude the reference")
        if len(set(self.manifest_refs)) != len(self.manifest_refs) or len(
            set(self.record_refs)
        ) != len(self.record_refs):
            raise ValueError("report sources must be unique")
        if len(set(self.categories)) != len(self.categories):
            raise ValueError("categories must be unique")
        if self.metric != "scalar" and len(self.categories) < 2:
            raise ValueError("categorical reports require at least two declared categories")
        if self.metric == "classification" and self.positive_label not in self.categories:
            raise ValueError("classification positive label must be declared")
        if self.ordinal_mapping is not None and set(self.ordinal_mapping) != set(self.categories):
            raise ValueError("ordinal mapping must cover all categories")
        return self
