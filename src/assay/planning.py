"""Pure snapshot-to-plan compilation and authorization."""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping
from decimal import Decimal
from typing import TypedDict

from pydantic import BaseModel

from assay._version import __version__
from assay.canonical import canonical_json, digest_bytes
from assay.models import (
    CellCoordinate,
    EvaluationCoordinate,
    Exclusion,
    ExecutionPlan,
    ExecutionPlanV2,
    PriceEstimate,
    RuntimeProfile,
    StudySnapshot,
    parse_execution_plan,
)
from assay.references import walk_closure
from assay.store import ObjectStore


class AuthorizationError(ValueError):
    pass


class _PlanCommon(TypedDict):
    snapshot_ref: str
    worker_repeats: int
    concurrency: int
    exclusions: tuple[Exclusion, ...]
    cells: tuple[CellCoordinate, ...]
    evaluations: tuple[EvaluationCoordinate, ...]
    declaration_hashes: tuple[str, ...]
    execution_conditions_ref: str
    cost_estimate: PriceEstimate
    arm_cost_estimates: dict[str, PriceEstimate]


def _hash(value: object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return digest_bytes(canonical_json(value))


def _compile_common(
    snapshot: StudySnapshot,
    *,
    snapshot_ref: str,
    worker_repeats: int,
    exclusions: Collection[Exclusion],
    cost_estimate: PriceEstimate | None,
    concurrency: int,
    arm_cost_estimates: Mapping[str, PriceEstimate] | None,
) -> _PlanCommon:
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
    return {
        "snapshot_ref": snapshot_ref,
        "worker_repeats": worker_repeats,
        "concurrency": concurrency,
        "exclusions": tuple(sorted(exclusions, key=lambda item: (item.subject_id, item.arm_id))),
        "cells": cells,
        "evaluations": evaluations,
        "declaration_hashes": tuple(sorted(_hash(item) for item in declarations)),
        "execution_conditions_ref": _hash(
            [arm.conditions for arm in sorted(snapshot.arms, key=lambda x: x.id)]
        ),
        "cost_estimate": total,
        "arm_cost_estimates": estimates,
    }


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
    """Compile an ``assay-execution-plan/0.1.0`` plan pinned to a Jig revision."""
    common = _compile_common(
        snapshot,
        snapshot_ref=snapshot_ref,
        worker_repeats=worker_repeats,
        exclusions=exclusions,
        cost_estimate=cost_estimate,
        concurrency=concurrency,
        arm_cost_estimates=arm_cost_estimates,
    )
    return ExecutionPlan(**common, jig_revision=jig_revision, assay_version=__version__)


def compile_plan_v2(
    snapshot: StudySnapshot,
    *,
    snapshot_ref: str,
    worker_repeats: int,
    exclusions: Collection[Exclusion] = (),
    runtime: RuntimeProfile,
    cost_estimate: PriceEstimate | None = None,
    concurrency: int = 4,
    arm_cost_estimates: Mapping[str, PriceEstimate] | None = None,
) -> ExecutionPlanV2:
    """Compile an ``assay-execution-plan/0.2.0`` plan bound to a generic runtime.

    ``runtime`` binds a backend-neutral identity to its complete, content-addressed
    configuration; unlike 0.1.0's ``jig_revision`` string, this generalizes to any
    future backend (e.g. Pier) without mixing legacy and generic runtime fields.
    """
    common = _compile_common(
        snapshot,
        snapshot_ref=snapshot_ref,
        worker_repeats=worker_repeats,
        exclusions=exclusions,
        cost_estimate=cost_estimate,
        concurrency=concurrency,
        arm_cost_estimates=arm_cost_estimates,
    )
    return ExecutionPlanV2(**common, runtime=runtime, assay_version=__version__)


def validate_plan_snapshot(plan: ExecutionPlan | ExecutionPlanV2, snapshot: StudySnapshot) -> None:
    """Recompile every governed plan field; a matching snapshot hash alone is insufficient."""
    if isinstance(plan, ExecutionPlanV2):
        expected: ExecutionPlan | ExecutionPlanV2 = compile_plan_v2(
            snapshot,
            snapshot_ref=plan.snapshot_ref,
            worker_repeats=plan.worker_repeats,
            exclusions=plan.exclusions,
            runtime=plan.runtime,
            cost_estimate=plan.cost_estimate,
            concurrency=plan.concurrency,
            arm_cost_estimates=plan.arm_cost_estimates,
        )
    else:
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


def require_runtime_closure(store: ObjectStore, plan: ExecutionPlan | ExecutionPlanV2) -> None:
    """Reject a 0.2.0 plan whose generic runtime configuration is missing or malformed.

    A 0.1.0 plan pins its runtime by an opaque ``jig_revision`` string with nothing to
    resolve, so this is a no-op for it. Both execution and reporting must call this
    before trusting an authorized plan, since neither path recompiles the plan and
    would otherwise silently proceed against a runtime that was never fully declared.
    """
    if isinstance(plan, ExecutionPlanV2):
        walk_closure(store, {(plan.runtime.configuration_ref, "data")})


def authorize(plan_bytes: bytes, authorization: str) -> ExecutionPlan | ExecutionPlanV2:
    actual = digest_bytes(plan_bytes)
    if authorization != actual:
        raise AuthorizationError(f"authorization {authorization} does not match plan {actual}")
    plan = parse_execution_plan(json.loads(plan_bytes))
    if canonical_json(plan.model_dump(mode="json")) != plan_bytes:
        raise AuthorizationError("authorized plan must be complete canonical wire JSON")
    return plan
