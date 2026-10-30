"""Failure taxonomy and the exhaustive, non-judgmental first classification pass."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal, assert_never

from pydantic import Field, TypeAdapter

from assay.investigations.workflow_correctness import Attribution, PreflightResult, Verdict
from assay.pier_protocol import CandidateCause, InfrastructureCause


@dataclass(frozen=True, kw_only=True)
class OperatorJudgment:
    assigned_by: str
    trace_digest: str

    def __post_init__(self) -> None:
        if (
            not self.assigned_by.strip()
            or not self.trace_digest.startswith("sha256:")
            or len(self.trace_digest) != 71
        ):
            raise ValueError("operator identity and trace digest are required")


@dataclass(frozen=True, kw_only=True)
class CouldNotDiscoverRelevantCode(OperatorJudgment):
    tag: Literal["could_not_discover_relevant_code"] = "could_not_discover_relevant_code"


@dataclass(frozen=True, kw_only=True)
class WrongAbstractionOrPlan(OperatorJudgment):
    tag: Literal["wrong_abstraction_or_plan"] = "wrong_abstraction_or_plan"


@dataclass(frozen=True, kw_only=True)
class MissedIntegrationPoint(OperatorJudgment):
    tag: Literal["missed_integration_point"] = "missed_integration_point"


@dataclass(frozen=True, kw_only=True)
class CodeGenerationDefect(OperatorJudgment):
    tag: Literal["code_generation_defect"] = "code_generation_defect"


@dataclass(frozen=True, kw_only=True)
class InvalidVerificationClaim(OperatorJudgment):
    tag: Literal["invalid_verification_claim"] = "invalid_verification_claim"


@dataclass(frozen=True)
class HarnessOrProviderFailure:
    tag: Literal["harness_or_provider_failure"] = "harness_or_provider_failure"


@dataclass(frozen=True)
class Timeout:
    tag: Literal["timeout"] = "timeout"


@dataclass(frozen=True, kw_only=True)
class AmbiguousFixture(OperatorJudgment):
    tag: Literal["ambiguous_fixture"] = "ambiguous_fixture"


type OperatorCategory = (
    CouldNotDiscoverRelevantCode | WrongAbstractionOrPlan | MissedIntegrationPoint
    | CodeGenerationDefect | InvalidVerificationClaim | AmbiguousFixture
)
type MechanicalCategory = HarnessOrProviderFailure | Timeout
type FailureCategory = Annotated[OperatorCategory | MechanicalCategory, Field(discriminator="tag")]
_category_adapter: TypeAdapter[OperatorCategory | MechanicalCategory] = TypeAdapter(
    FailureCategory
)


def parse_category(value: object) -> FailureCategory:
    """Reject an unknown tag or missing operator provenance at the wire boundary."""
    return _category_adapter.validate_python(value)


@dataclass(frozen=True)
class Submitted:
    kind: Literal["submitted"] = "submitted"


@dataclass(frozen=True)
class CandidateStopped:
    cause: CandidateCause
    kind: Literal["candidate_stopped"] = "candidate_stopped"


@dataclass(frozen=True)
class InfrastructureStopped:
    cause: InfrastructureCause
    kind: Literal["infrastructure_stopped"] = "infrastructure_stopped"


@dataclass(frozen=True)
class CoreStopped:
    error_type: str
    kind: Literal["core_stopped"] = "core_stopped"


@dataclass(frozen=True)
class NotStarted:
    kind: Literal["not_started"] = "not_started"


type StopCause = Submitted | CandidateStopped | InfrastructureStopped | CoreStopped | NotStarted


@dataclass(frozen=True)
class GroupVerdict:
    status: Literal["passed", "failed", "unavailable"]
    cause: str | None = None


@dataclass(frozen=True)
class EvaluatorVerdict:
    value: Verdict
    groups: tuple[GroupVerdict, ...]
    cause: str | None = None
    preflight: PreflightResult | None = None
    attribution: Attribution | None = None


@dataclass(frozen=True)
class Passed:
    kind: Literal["passed"] = "passed"


@dataclass(frozen=True)
class NeedsOperatorJudgment:
    distinction: Literal["invalid_or_incomplete", "valid_but_wrong"]
    kind: Literal["needs_operator_judgment"] = "needs_operator_judgment"


type Classification = MechanicalCategory | Passed | NeedsOperatorJudgment


def classify(stop: StopCause, verdict: EvaluatorVerdict | None) -> Classification:
    """Assign mechanical causes; leave trace interpretation to an identified operator."""
    if isinstance(stop, NotStarted | CoreStopped):
        return HarnessOrProviderFailure()
    if isinstance(stop, InfrastructureStopped):
        match stop.cause:
            case "harness_deadline":
                return Timeout()
            case (
                "cancelled" | "container_start" | "enforcement"
                | "unexpected_exception" | "mismatched_cell"
            ):
                return HarnessOrProviderFailure()
            case unknown_infrastructure:
                assert_never(unknown_infrastructure)
    if isinstance(stop, CandidateStopped):
        match stop.cause:
            case "candidate_test_timeout" | "agent_deadline":
                return Timeout()
            case (
                "no_submission" | "symlink_submission" | "traversal" | "escaping_symlink"
                | "binary_payload" | "oversized_artifact" | "aggregate_artifact_limit"
                | "entry_limit" | "out_of_scope_edit" | "tampering" | "nonzero_exit"
                | "storage_exhausted" | "memory_limit" | "invalid_tool_output_encoding"
                | "patch_capture_conflict" | "non_utf8_path"
                | "workspace_capture_permission" | "hard_link_submission"
            ):
                return NeedsOperatorJudgment("invalid_or_incomplete")
            case unknown_candidate:
                assert_never(unknown_candidate)
    if isinstance(stop, Submitted):
        if verdict is None or verdict.value == "unavailable":
            return HarnessOrProviderFailure()
        if verdict.value == "correct":
            return Passed()
        if verdict.value == "incorrect":
            invalid = (
                verdict.cause == "patch_rejected"
                or verdict.preflight is not None and verdict.preflight.status != "passed"
                or verdict.preflight is None and bool(verdict.groups)
                and all(group.status == "unavailable" for group in verdict.groups)
            )
            return NeedsOperatorJudgment(
                "invalid_or_incomplete" if invalid else "valid_but_wrong"
            )
        assert_never(verdict.value)
    assert_never(stop)


def operator_category(
    tag: Literal[
        "could_not_discover_relevant_code", "wrong_abstraction_or_plan",
        "missed_integration_point", "code_generation_defect", "invalid_verification_claim",
        "ambiguous_fixture",
    ], *, assigned_by: str, trace_digest: str,
) -> OperatorCategory:
    """Record an attributed post-run judgment against the exact trace bytes."""
    match tag:
        case "could_not_discover_relevant_code":
            return CouldNotDiscoverRelevantCode(assigned_by=assigned_by, trace_digest=trace_digest)
        case "wrong_abstraction_or_plan":
            return WrongAbstractionOrPlan(assigned_by=assigned_by, trace_digest=trace_digest)
        case "missed_integration_point":
            return MissedIntegrationPoint(assigned_by=assigned_by, trace_digest=trace_digest)
        case "code_generation_defect":
            return CodeGenerationDefect(assigned_by=assigned_by, trace_digest=trace_digest)
        case "invalid_verification_claim":
            return InvalidVerificationClaim(assigned_by=assigned_by, trace_digest=trace_digest)
        case "ambiguous_fixture":
            return AmbiguousFixture(assigned_by=assigned_by, trace_digest=trace_digest)
        case unknown:
            assert_never(unknown)
