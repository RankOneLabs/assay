"""Pure snapshot-to-plan compilation and authorization."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from decimal import Decimal

from pydantic import BaseModel

from assay._version import __version__
from assay.canonical import canonical_json, digest_bytes
from assay.models import (
    CellCoordinate,
    EvaluationCoordinate,
    Exclusion,
    ExecutionPlan,
    PriceEstimate,
    StudySnapshot,
)


class AuthorizationError(ValueError):
    pass


def _hash(value: object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return digest_bytes(canonical_json(value))


def compile_plan(
    snapshot: StudySnapshot,
    *,
    snapshot_ref: str,
    worker_repeats: int,
    exclusions: Collection[Exclusion] = (),
    jig_revision: str,
    cost_estimate: PriceEstimate | None = None,
    concurrency: int = 4,
    arm_cost_estimates: Mapping[str, PriceEstimate] | None = None,
) -> ExecutionPlan:
    snapshot = StudySnapshot.model_validate(snapshot.model_dump(mode="json"))
    if _hash(snapshot) != snapshot_ref:
        raise ValueError("snapshot_ref does not match the canonical snapshot")
    if worker_repeats < 1:
        raise ValueError("worker_repeats must be positive")
    excluded = {(item.subject_id, item.arm_id) for item in exclusions}
    realization = {(item.subject_id, item.arm_id): item for item in snapshot.realizations}
    if len(excluded) != len(exclusions) or not excluded <= set(realization):
        raise ValueError("exclusions must be unique existing subject/arm pairs")
    subjects = sorted(snapshot.subjects, key=lambda item: item.id)
    arms = sorted(snapshot.arms, key=lambda item: item.id)
    schedules = {arm.conditions.get("assay_execution_schedule") for arm in arms}
    if schedules == {None}:
        ordered_coordinates = (
            (subject, arm, repeat)
            for subject in subjects
            for arm in arms
            if (subject.id, arm.id) not in excluded
            for repeat in range(worker_repeats)
        )
    elif schedules == {"subject-counterbalanced-v1"} and len(arms) == 2:
        ordered_coordinates = (
            (subject, arm, repeat)
            for subject_index, subject in enumerate(subjects)
            for repeat in range(worker_repeats)
            for arm in (arms if (subject_index + repeat) % 2 == 0 else list(reversed(arms)))
            if (subject.id, arm.id) not in excluded
        )
    else:
        raise ValueError("execution schedule must be absent or a common supported value")
    cells = tuple(
        CellCoordinate(
            subject_id=subject.id,
            arm_id=arm.id,
            worker_repeat=repeat,
            realization_ref=realization[(subject.id, arm.id)].artifact_ref,
        )
        for subject, arm, repeat in ordered_coordinates
    )
    evaluations = tuple(
        EvaluationCoordinate(cell_id=cell.id, evaluator_id=evaluator.id, evaluator_repeat=repeat)
        for cell in cells
        for evaluator in sorted(snapshot.evaluators, key=lambda item: item.id)
        for repeat in range(evaluator.repeats)
    )
    declarations = [*snapshot.arms, *snapshot.evaluators]
    estimates = (
        dict(arm_cost_estimates)
        if arm_cost_estimates is not None
        else {arm.id: PriceEstimate(amount=None, coverage="unavailable") for arm in snapshot.arms}
    )
    if set(estimates) != {arm.id for arm in snapshot.arms}:
        raise ValueError("arm cost estimates must cover the declared arms exactly")
    estimates = {
        key: PriceEstimate.model_validate(value.model_dump(mode="json"))
        for key, value in estimates.items()
    }
    currencies = {value.currency for value in estimates.values() if value.amount is not None}
    if len(currencies) > 1:
        raise ValueError("arm estimates must use a single reporting currency")
    available = [value for value in estimates.values() if value.amount is not None]
    coverage = {value.coverage for value in estimates.values()}
    total = PriceEstimate(amount=None, coverage="unavailable")
    if available:
        total = PriceEstimate(
            amount=float(sum(Decimal(str(value.amount)) for value in available)),
            currency=next(iter(currencies)),
            coverage=next(iter(coverage)) if len(coverage) == 1 else "mixed",
        )
    if cost_estimate is not None and cost_estimate != total:
        raise ValueError("total cost estimate must equal the derived arm estimates")
    return ExecutionPlan(
        snapshot_ref=snapshot_ref,
        worker_repeats=worker_repeats,
        concurrency=concurrency,
        exclusions=tuple(sorted(exclusions, key=lambda item: (item.subject_id, item.arm_id))),
        cells=cells,
        evaluations=evaluations,
        declaration_hashes=tuple(sorted(_hash(item) for item in declarations)),
        execution_conditions_ref=_hash(
            [arm.conditions for arm in sorted(snapshot.arms, key=lambda x: x.id)]
        ),
        cost_estimate=total,
        arm_cost_estimates=estimates,
        jig_revision=jig_revision,
        assay_version=__version__,
    )


def validate_plan_snapshot(plan: ExecutionPlan, snapshot: StudySnapshot) -> None:
    """Recompile every governed plan field; a matching snapshot hash alone is insufficient."""
    expected = compile_plan(
        snapshot,
        snapshot_ref=plan.snapshot_ref,
        worker_repeats=plan.worker_repeats,
        exclusions=plan.exclusions,
        jig_revision=plan.jig_revision,
        cost_estimate=plan.cost_estimate,
        concurrency=plan.concurrency,
        arm_cost_estimates=plan.arm_cost_estimates,
    )
    if expected != plan:
        raise ValueError("plan differs from the deterministic snapshot compilation")


def authorize(plan_bytes: bytes, authorization: str) -> ExecutionPlan:
    actual = digest_bytes(plan_bytes)
    if authorization != actual:
        raise AuthorizationError(f"authorization {authorization} does not match plan {actual}")
    plan = ExecutionPlan.model_validate_json(plan_bytes)
    if canonical_json(plan.model_dump(mode="json")) != plan_bytes:
        raise AuthorizationError("authorized plan must be complete canonical wire JSON")
    return plan
