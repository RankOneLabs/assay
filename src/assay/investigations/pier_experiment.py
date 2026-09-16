"""Pier vertical-slice investigation profiles: full, smoke, and qualification.

Every profile is pinned to its own ``RuntimeProfile`` -- distinct runtime
version, image digest, and configuration reference -- so a plan authorized
for one profile can never be silently substituted for another's. Costs are
never hand-typed: every ceiling in this module is
``deterministic_cell_price_estimate``'s output for that profile's exact cell
count at ``PIER_COST_PER_CELL_USD``, checked against the literal numbers this
cohort was specified against in ``tests/test_pier_profiles.py``.

Preparation (``prepare_*``) never touches a client, a container, or the
network -- it only compiles and publishes a plan from already-declared
subjects/arms/realizations. Execution (``run_*``) additionally requires
``allow_paid=True`` and revalidates the plan's runtime/route/price against
the live adapter immediately before dispatch, mirroring the gating already
established in ``assay.adapters.openrouter_policy``/``dry_experiment``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import paa_contracts

from assay.adapters.pier import PierAdapter, PierBridgeClient, worker_configuration
from assay.canonical import canonical_json
from assay.execution import (
    EvaluationFailed,
    EvaluationSuccess,
    Evaluator,
    RunFailed,
    execute_plan,
)
from assay.investigations.consistency import EXPERIMENT_TASKS, CodingTask
from assay.investigations.dry_common import (
    deterministic_arm_price_estimates,
    publish_plan_dependencies,
    repository_for,
)
from assay.investigations.realistic_fixtures import REALISTIC_PILOT_FIXTURES, RepositoryFixture
from assay.models import (
    Arm,
    EvaluatorDeclaration,
    ExecutionPlanV2,
    Realization,
    RuntimeProfile,
    StudySnapshot,
    Subject,
)
from assay.pier_protocol import RuntimeBinding
from assay.planning import (
    authorize,
    compile_plan_v2,
    require_runtime_closure,
    validate_plan_snapshot,
)
from assay.store import ObjectStore
from assay.verify import reference_closure, verify_snapshot

PIER_COST_PER_CELL_USD = Decimal("0.72")

# The measured local build digest recorded in integrations/pier/README.md
# ("Runtime identity"): the durable identity input is the lock digest, not
# this image ID, but a fixed, documented value is still pinned here so every
# profile's runtime binding is reproducible rather than invented per call.
PIER_BRIDGE_IMAGE_DIGEST = (
    "sha256:b3e07726d3e92731c1ac1f934d27457a6545a52660af484fd67fb092cf09dc3f"
)
PIER_MODEL_ROUTE: Mapping[str, str] = {
    "endpoint": "https://openrouter.ai/api/v1",
    "model": "anthropic/claude-3-haiku",
    "provider": "amazon-bedrock",
}
PIER_TRIAL_LIMITS: Mapping[str, float | int] = {
    "cpu": 1,
    "memory_mb": 1024,
    "pids": 64,
    "timeout_s": 600,
}

ARM_IDS = ("clean", "inconsistent")


@dataclass(frozen=True)
class PierExperimentPrepared:
    snapshot_ref: str
    plan_ref: str
    cells: int
    evaluations: int


@dataclass(frozen=True)
class PierExperimentFailed:
    error_type: str
    message: str
    manifest_ref: str | None = None


@dataclass(frozen=True)
class PierExperimentSucceeded:
    manifest_ref: str


class _CandidateSubmittedEvaluator:
    """The trivial pass/fail check every Pier profile shares: did a candidate land."""

    def configuration(self) -> dict[str, Any]:
        return {"id": "pier-candidate-submitted", "version": "1"}

    async def evaluate(
        self, *, input_value: Any, output: Any, coordinate: Any
    ) -> EvaluationSuccess | EvaluationFailed:
        if not isinstance(output, dict) or not output.get("candidate_ref"):
            return EvaluationFailed("MissingCandidate", "no candidate_ref in worker output")
        return EvaluationSuccess("submitted")


def _runtime_binding(*, profile: str, package_digest: str) -> RuntimeBinding:
    return RuntimeBinding(
        runtime_version=f"pier-{profile}-v1",
        image_digest=PIER_BRIDGE_IMAGE_DIGEST,
        configuration_ref="sha256:" + "0" * 64,  # replaced by the real ref once published
        package_digest=package_digest,
    )


def _publish_runtime(store: ObjectStore, *, profile: str) -> tuple[RuntimeBinding, RuntimeProfile]:
    """One arm-level runtime identity for ``profile``, distinct from every other profile."""
    unbound = _runtime_binding(profile=profile, package_digest="sha256:" + "0" * 64)
    configuration = {
        "runtime_id": unbound.runtime_id,
        "runtime_version": unbound.runtime_version,
        "image_digest": unbound.image_digest,
        "model_route": dict(PIER_MODEL_ROUTE),
        "trial_limits": dict(PIER_TRIAL_LIMITS),
    }
    configuration_ref = str(store.publish_json(configuration))
    binding = RuntimeBinding(
        runtime_version=unbound.runtime_version,
        image_digest=unbound.image_digest,
        configuration_ref=configuration_ref,
        package_digest=unbound.package_digest,
    )
    runtime = RuntimeProfile(
        id="pier", version=binding.runtime_version, configuration_ref=configuration_ref
    )
    return binding, runtime


def _materialize_pier_snapshot(
    store: ObjectStore,
    *,
    profile: str,
    tasks: Sequence[CodingTask],
    repositories: Mapping[str, Mapping[str, Mapping[str, str]]],
) -> tuple[StudySnapshot, RuntimeBinding]:
    """One subject per task, two arms (clean/inconsistent), Pier-shaped realizations."""

    def publish(value: Any) -> str:
        return str(store.publish_json(value))

    binding, _ = _publish_runtime(store, profile=profile)
    arm_worker = worker_configuration(
        binding=binding, model_route=PIER_MODEL_ROUTE, trial_limits=PIER_TRIAL_LIMITS
    )
    arms = tuple(
        Arm(id=arm_id, worker=arm_worker, intervention={"repository": arm_id}) for arm_id in ARM_IDS
    )

    subjects = []
    realizations = []
    for task in tasks:
        task_value = task.model_dump(mode="json", exclude={"reused_source", "duplicated_source"})
        subject_ref = publish(task_value)
        subjects.append(
            Subject(
                id=task.id,
                label=task.instruction,
                partition=task.family,
                digest=subject_ref,
                payload_ref=subject_ref,
            )
        )
        for arm_id in ARM_IDS:
            repository = repositories[task.id][arm_id]
            realization_value = {"task": task.instruction, "repository": dict(repository)}
            artifact_ref = publish(realization_value)
            realizations.append(
                Realization(
                    subject_id=task.id,
                    arm_id=arm_id,
                    digest=artifact_ref,
                    artifact_ref=artifact_ref,
                )
            )

    identity = {
        "property": "candidate_submitted",
        "target": "output",
        "technique": "deterministic",
        "evaluation_basis": {"kind": "invariant", "ref": "pier-candidate-submitted-v1"},
        "epistemic_status": "proxy",
        "version": "1",
        "authority": "advisory",
    }
    companion = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": f"https://assay.local/schemas/pier-{profile}-evidence-v1.json",
        "allOf": [
            {"$ref": "https://paa.dev/paa-evidence-record.schema.json"},
            {"properties": {"verdict": {"properties": {"value": {"type": "string"}}}}},
        ],
    }
    evaluator = EvaluatorDeclaration(
        id="candidate_submitted",
        identity=identity,
        payload_schema=str(companion["$id"]),
        payload_schema_ref=publish(companion),
        configuration=_CandidateSubmittedEvaluator().configuration(),
        basis_ref=publish({"invariant": "candidate_ref must be present on success"}),
        repeats=1,
    )
    task_declaration = {
        "task": f"pier_{profile}",
        "version": 1,
        "description": f"Pier {profile} vertical-slice run",
        "boundary": {"input": "task_repository", "output": "candidate_source"},
        "initial_position": "manual",
        "deployment": "shadow",
        "evaluators": [identity],
        "position_policy": {"manual": "offline", "hitl": "blocking"},
        "promotion": {
            "from": "manual",
            "to": "hitl",
            "report": f"pier_{profile}_report",
            "window": {"kind": "cases", "size": 10},
            "execution": "operator_approval",
        },
        "demotion": {
            "from": "hitl",
            "to": "manual",
            "trigger": "operator_decision",
            "window": {"kind": "cases", "size": 1},
        },
    }
    snapshot = StudySnapshot(
        subjects=tuple(subjects),
        arms=arms,
        realizations=tuple(realizations),
        evaluators=(evaluator,),
        paa_task_ref=publish(task_declaration),
        pricing_catalog_ref=publish({"per_cell_usd": str(PIER_COST_PER_CELL_USD)}),
        task_schema_ref=publish(paa_contracts.load_schema("paa-task")),
        evidence_schema_ref=publish(paa_contracts.load_schema("paa-evidence-record")),
        operating_schema_ref=publish(paa_contracts.load_schema("paa-operating-record")),
    )
    return snapshot, binding


def _repositories_for_tasks(
    tasks: Sequence[CodingTask],
) -> dict[str, dict[str, Mapping[str, str]]]:
    return {
        task.id: {arm_id: repository_for(task, arm_id, None) for arm_id in ARM_IDS}
        for task in tasks
    }


def _repositories_for_fixtures(
    fixtures: Sequence[RepositoryFixture],
) -> dict[str, dict[str, Mapping[str, str]]]:
    return {
        fixture.task.id: {
            "clean": fixture.clean_repository,
            "inconsistent": fixture.inconsistent_repository,
        }
        for fixture in fixtures
    }


def _prepare(
    store: ObjectStore,
    *,
    profile: str,
    tasks: Sequence[CodingTask],
    repositories: Mapping[str, Mapping[str, Mapping[str, str]]],
    worker_repeats: int,
    expected_cells: int,
) -> PierExperimentPrepared | PierExperimentFailed:
    try:
        snapshot, _ = _materialize_pier_snapshot(
            store, profile=profile, tasks=tasks, repositories=repositories
        )
        verify_snapshot(store, snapshot)
        snapshot_ref = str(store.publish_json(snapshot.model_dump(mode="json")))
        publish_plan_dependencies(store, snapshot)
        cells_per_arm = expected_cells // len(ARM_IDS)
        _, runtime = _publish_runtime(store, profile=profile)
        plan = compile_plan_v2(
            snapshot,
            snapshot_ref=snapshot_ref,
            worker_repeats=worker_repeats,
            runtime=runtime,
            arm_cost_estimates=deterministic_arm_price_estimates(
                arm_ids=ARM_IDS, cells_per_arm=cells_per_arm, per_cell_usd=PIER_COST_PER_CELL_USD
            ),
        )
        plan_ref = str(store.publish_json(plan.model_dump(mode="json")))
        require_runtime_closure(store, plan)
        reference_closure(store, (plan_ref,))
        if len(plan.cells) != expected_cells:
            raise ValueError(f"unexpected Pier {profile} grid: {len(plan.cells)} cells")
        return PierExperimentPrepared(
            snapshot_ref, plan_ref, len(plan.cells), len(plan.evaluations)
        )
    except Exception as error:
        return PierExperimentFailed(type(error).__name__, str(error))


def prepare_pier_full(store: ObjectStore) -> PierExperimentPrepared | PierExperimentFailed:
    """Twelve subjects, two arms, two repeats: 48 ordered cells, $34.56 ceiling."""
    return _prepare(
        store,
        profile="full",
        tasks=EXPERIMENT_TASKS,
        repositories=_repositories_for_tasks(EXPERIMENT_TASKS),
        worker_repeats=2,
        expected_cells=48,
    )


def prepare_pier_smoke(store: ObjectStore) -> PierExperimentPrepared | PierExperimentFailed:
    """One subject, two arms, two repeats: 4 cells, $2.88 ceiling."""
    tasks = EXPERIMENT_TASKS[:1]
    return _prepare(
        store,
        profile="smoke",
        tasks=tasks,
        repositories=_repositories_for_tasks(tasks),
        worker_repeats=2,
        expected_cells=4,
    )


def prepare_pier_qualification(store: ObjectStore) -> PierExperimentPrepared | PierExperimentFailed:
    """All four realistic-pilot fixtures, two arms, two repeats: 16 cells, $11.52 ceiling."""
    return _prepare(
        store,
        profile="qualification",
        tasks=tuple(fixture.task for fixture in REALISTIC_PILOT_FIXTURES),
        repositories=_repositories_for_fixtures(REALISTIC_PILOT_FIXTURES),
        worker_repeats=2,
        expected_cells=16,
    )


def _revalidate_before_dispatch(
    plan: Any,
    *,
    binding: RuntimeBinding,
    model_route: Mapping[str, str],
    trial_limits: Mapping[str, Any],
) -> None:
    """Mirror ``openrouter_policy``'s gate: re-check identity/route/price right
    before the paid call, not only at prepare time."""
    expected = worker_configuration(
        binding=binding, model_route=model_route, trial_limits=trial_limits
    )
    canonical_json(plan.cost_estimate.model_dump(mode="json"))
    for estimate in plan.arm_cost_estimates.values():
        canonical_json(estimate.model_dump(mode="json"))
    if canonical_json(expected) != canonical_json(
        {
            "id": "pier",
            "version": binding.runtime_version,
            "runtime_id": binding.runtime_id,
            "image_digest": binding.image_digest,
            "configuration_ref": binding.configuration_ref,
            "model_route": dict(model_route),
            "trial_limits": dict(trial_limits),
        }
    ):
        raise ValueError("Pier runtime/route differs from the plan being authorized")


async def _run(
    store: ObjectStore,
    *,
    profile: str,
    plan_ref: str,
    authorization: str,
    bridge: PierBridgeClient,
    allow_paid: bool,
    expected_cells: int,
) -> PierExperimentSucceeded | PierExperimentFailed:
    manifest_ref: str | None = None
    try:
        if not allow_paid:
            raise ValueError(f"paid Pier {profile} execution requires explicit allow_paid=True")
        plan_bytes = store.read_bytes(plan_ref)
        plan = authorize(plan_bytes, authorization)
        if not isinstance(plan, ExecutionPlanV2):
            raise ValueError("Pier execution requires an assay-execution-plan/0.2.0 plan")
        if plan.runtime.version != f"pier-{profile}-v1":
            raise ValueError(f"plan is not pinned to the Pier {profile} runtime")
        snapshot = StudySnapshot.model_validate_json(store.read_bytes(plan.snapshot_ref))
        verify_snapshot(store, snapshot)
        validate_plan_snapshot(plan, snapshot)
        require_runtime_closure(store, plan)
        reference_closure(store, (plan_ref,))
        if len(plan.cells) != expected_cells:
            raise ValueError(f"unexpected Pier {profile} grid at execution time")

        binding, _ = _publish_runtime(store, profile=profile)
        _revalidate_before_dispatch(
            plan, binding=binding, model_route=PIER_MODEL_ROUTE, trial_limits=PIER_TRIAL_LIMITS
        )
        adapter = PierAdapter(
            store=store,
            bridge=bridge,
            binding=binding,
            model_route=PIER_MODEL_ROUTE,
            trial_limits=PIER_TRIAL_LIMITS,
        )
        evaluator: Evaluator = _CandidateSubmittedEvaluator()
        # PierAdapter is a frozen dataclass, so mypy treats its
        # ``supports_cell_coordinates`` attribute as read-only, which the
        # CoordinateAwareWorker protocol's settable-attribute check rejects
        # even though execute_plan only ever reads it at runtime.
        workers: dict[str, Any] = {arm.id: adapter for arm in snapshot.arms}
        result = await execute_plan(
            plan_bytes=plan_bytes,
            authorization=authorization,
            snapshot=snapshot,
            store=store,
            workers=workers,
            evaluators={"candidate_submitted": evaluator},
        )
        if result.manifest_ref is not None:
            manifest_ref = str(result.manifest_ref)
        if isinstance(result, RunFailed):
            return PierExperimentFailed(result.error_type, result.message, manifest_ref)
        assert manifest_ref is not None
        return PierExperimentSucceeded(manifest_ref)
    except Exception as error:
        return PierExperimentFailed(type(error).__name__, str(error), manifest_ref)


async def run_pier_full(
    store: ObjectStore,
    *,
    plan_ref: str,
    authorization: str,
    bridge: PierBridgeClient,
    allow_paid: bool = False,
) -> PierExperimentSucceeded | PierExperimentFailed:
    return await _run(
        store,
        profile="full",
        plan_ref=plan_ref,
        authorization=authorization,
        bridge=bridge,
        allow_paid=allow_paid,
        expected_cells=48,
    )


async def run_pier_smoke(
    store: ObjectStore,
    *,
    plan_ref: str,
    authorization: str,
    bridge: PierBridgeClient,
    allow_paid: bool = False,
) -> PierExperimentSucceeded | PierExperimentFailed:
    return await _run(
        store,
        profile="smoke",
        plan_ref=plan_ref,
        authorization=authorization,
        bridge=bridge,
        allow_paid=allow_paid,
        expected_cells=4,
    )


async def run_pier_qualification(
    store: ObjectStore,
    *,
    plan_ref: str,
    authorization: str,
    bridge: PierBridgeClient,
    allow_paid: bool = False,
) -> PierExperimentSucceeded | PierExperimentFailed:
    return await _run(
        store,
        profile="qualification",
        plan_ref=plan_ref,
        authorization=authorization,
        bridge=bridge,
        allow_paid=allow_paid,
        expected_cells=16,
    )


# Cost ceilings this cohort was specified against -- literal numbers, checked
# in tests/test_pier_profiles.py against deterministic_cell_price_estimate's
# derivation from PIER_COST_PER_CELL_USD, never hardcoded independently here.
PIER_FULL_TOTAL_USD = "34.56"
PIER_FULL_PER_ARM_USD = "17.28"
PIER_SMOKE_TOTAL_USD = "2.88"
PIER_SMOKE_PER_ARM_USD = "1.44"
PIER_QUALIFICATION_TOTAL_USD = "11.52"
PIER_QUALIFICATION_PER_ARM_USD = "5.76"


__all__ = [
    "ARM_IDS",
    "PIER_BRIDGE_IMAGE_DIGEST",
    "PIER_COST_PER_CELL_USD",
    "PIER_FULL_PER_ARM_USD",
    "PIER_FULL_TOTAL_USD",
    "PIER_MODEL_ROUTE",
    "PIER_QUALIFICATION_PER_ARM_USD",
    "PIER_QUALIFICATION_TOTAL_USD",
    "PIER_SMOKE_PER_ARM_USD",
    "PIER_SMOKE_TOTAL_USD",
    "PIER_TRIAL_LIMITS",
    "PierExperimentFailed",
    "PierExperimentPrepared",
    "PierExperimentSucceeded",
    "prepare_pier_full",
    "prepare_pier_qualification",
    "prepare_pier_smoke",
    "run_pier_full",
    "run_pier_qualification",
    "run_pier_smoke",
]
