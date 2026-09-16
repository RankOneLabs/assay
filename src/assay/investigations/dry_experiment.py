"""Prepared, explicitly authorized 12-subject DRY consistency experiment."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from assay._version import __version__
from assay.adapters.consistency import ClientFactory, ConsistencyWorker, PilotSettings, render_input
from assay.adapters.openrouter import HAIKU_BEDROCK, OpenRouterFactory
from assay.canonical import canonical_json, digest_bytes
from assay.execution import Evaluator, RunFailed, WorkerFailure, execute_plan
from assay.investigations.consistency import (
    CATEGORIES,
    EXPERIMENT_TASKS,
    CodingTask,
    StructuralEvaluator,
    materialize_consistency,
)
from assay.investigations.correctness import (
    CORRECTNESS_CATEGORIES,
    DockerPythonRunner,
    FunctionalCorrectnessEvaluator,
    SandboxFailure,
)
from assay.investigations.pilot import installed_jig_revision
from assay.models import ExecutionPlan, ReportConfig, StatisticalProfile, StudySnapshot
from assay.planning import authorize, compile_plan, validate_plan_snapshot
from assay.report_engine import persist_report
from assay.store import ObjectStore
from assay.verify import export_bundle, reference_closure, verify_bundle, verify_snapshot


@dataclass(frozen=True)
class DryExperimentPrepared:
    snapshot_ref: str
    plan_ref: str
    executions: int
    evaluations: int


@dataclass(frozen=True)
class DryExperimentFailed:
    error_type: str
    message: str
    manifest_ref: str | None = None
    abstraction_report_ref: str | None = None
    correctness_report_ref: str | None = None


@dataclass(frozen=True)
class DryExperimentSucceeded:
    manifest_ref: str
    abstraction_report_ref: str
    correctness_report_ref: str


def haiku_dry_settings() -> PilotSettings:
    """Forty-eight one-call cells, $2.88 conservative admission ceiling."""
    return PilotSettings(
        mode="paid",
        max_llm_calls=1,
        max_total_requests=48,
        max_spend_usd=Decimal("2.88"),
        request_cost_bound_usd=Decimal("0.06"),
        pricing_basis=(
            "OpenRouter inline usage.cost (USD credits), Claude 3 Haiku via "
            "Amazon Bedrock; 2026-09-11 rate caps $0.25/$1.25 per million "
            "input/output tokens; 48 one-call cells; no per-request fee; bound "
            "assumes <=200000 input and <=2048 output tokens, no BYOK, paid "
            "plugins, or additional charges; operator must validate before execution"
        ),
    )


def _validate_haiku_profile(factory: ClientFactory, settings: PilotSettings) -> None:
    if settings != haiku_dry_settings():
        raise ValueError("DRY experiment settings differ from the governed Haiku profile")
    if canonical_json(factory.configuration()) != canonical_json(
        OpenRouterFactory(HAIKU_BEDROCK).configuration()
    ):
        raise ValueError("DRY experiment provider differs from the governed Haiku profile")


def publish_plan_dependencies(store: ObjectStore, snapshot: StudySnapshot) -> None:
    """Publish every snapshot-derived object referenced directly by compile_plan."""
    for declaration in (*snapshot.arms, *snapshot.evaluators):
        store.publish_json(declaration.model_dump(mode="json"))
    store.publish_json([arm.conditions for arm in sorted(snapshot.arms, key=lambda item: item.id)])


def _repository_for(
    task: CodingTask,
    arm_id: str,
    repository_variants: Mapping[str, Mapping[str, Mapping[str, str]]] | None,
) -> dict[str, str]:
    if repository_variants is not None:
        try:
            return dict(repository_variants[task.id][arm_id])
        except KeyError as error:
            raise ValueError(f"missing {arm_id} repository for task {task.id}") from error
    example = task.reused_source if arm_id == "clean" else task.duplicated_source
    return {
        task.target_path: (
            task.helper_source + "\n" + example.replace("implement", "existing_feature")
        )
    }


def prepare_dry_experiment(
    store: ObjectStore,
    *,
    factory: ClientFactory,
    settings: PilotSettings,
    schemas: Mapping[str, dict[str, object]],
    runner: DockerPythonRunner,
) -> DryExperimentPrepared | DryExperimentFailed:
    """Materialize the full study without clients, containers, or provider calls."""
    try:
        if len(EXPERIMENT_TASKS) < 10:
            raise ValueError("DRY experiment requires at least ten subjects")
        _validate_haiku_profile(factory, settings)
        worker = ConsistencyWorker(factory, settings)
        correctness = FunctionalCorrectnessEvaluator(runner)
        snapshot = materialize_consistency(
            store,
            worker_configuration=worker.configuration("clean"),
            evaluator=StructuralEvaluator(),
            correctness_evaluator=correctness,
            schemas=schemas,
            tasks=EXPERIMENT_TASKS,
            evaluator_repeats=1,
            execution_schedule="subject-counterbalanced-v1",
        )
        verify_snapshot(store, snapshot)
        snapshot_ref = str(store.publish_json(snapshot.model_dump(mode="json")))
        publish_plan_dependencies(store, snapshot)
        plan = compile_plan(
            snapshot,
            snapshot_ref=snapshot_ref,
            worker_repeats=2,
            jig_revision=installed_jig_revision(),
            concurrency=1,
        )
        plan_ref = str(store.publish_json(plan.model_dump(mode="json")))
        reference_closure(store, (plan_ref,))
        if len(plan.cells) != 48 or len(plan.evaluations) != 96:
            raise ValueError("unexpected DRY experiment grid")
        return DryExperimentPrepared(snapshot_ref, plan_ref, len(plan.cells), len(plan.evaluations))
    except Exception as error:
        return DryExperimentFailed(type(error).__name__, str(error))


def _report_config(
    manifest_ref: str,
    record_refs: tuple[str, ...],
    *,
    evaluator_id: str,
    categories: tuple[str, ...],
) -> ReportConfig:
    return ReportConfig(
        manifest_refs=(manifest_ref,),
        record_refs=record_refs,
        reference_arm="inconsistent",
        candidates=("clean",),
        evaluator_id=evaluator_id,
        metric="ordinal",
        categories=categories,
        evaluator_repeat_aggregation="median",
        worker_repeat_aggregation="median",
        statistical_profile=StatisticalProfile(seed=7, bootstrap_samples=10_000),
        engine_version=__version__,
    )


def _validate_experiment_shape(
    store: ObjectStore,
    snapshot: StudySnapshot,
    plan: ExecutionPlan,
    *,
    tasks: Sequence[CodingTask] = EXPERIMENT_TASKS,
    repository_variants: Mapping[str, Mapping[str, Mapping[str, str]]] | None = None,
    expected_subjects: int = 12,
    expected_cells: int = 48,
    expected_evaluations: int = 96,
) -> None:
    tasks_by_id = {task.id: task for task in tasks}
    if len(tasks_by_id) != expected_subjects or {
        subject.id for subject in snapshot.subjects
    } != set(tasks_by_id):
        raise ValueError("consistency experiment subject population changed")
    if {arm.id for arm in snapshot.arms} != {"clean", "inconsistent"}:
        raise ValueError("consistency experiment arms changed")
    if {arm.conditions.get("assay_execution_schedule") for arm in snapshot.arms} != {
        "subject-counterbalanced-v1"
    }:
        raise ValueError("consistency experiment execution schedule changed")
    if any(item.repeats != 1 for item in snapshot.evaluators):
        raise ValueError("consistency experiment evaluator repeats changed")
    if (
        plan.concurrency != 1
        or plan.worker_repeats != 2
        or len(plan.cells) != expected_cells
        or len(plan.evaluations) != expected_evaluations
    ):
        raise ValueError("consistency experiment execution grid changed")

    subjects = {subject.id: subject for subject in snapshot.subjects}
    realizations = {
        (realization.subject_id, realization.arm_id): realization
        for realization in snapshot.realizations
    }
    for task in tasks:
        task_value = task.model_dump(mode="json", exclude={"reused_source", "duplicated_source"})
        subject_ref = digest_bytes(canonical_json(task_value))
        subject = subjects[task.id]
        if (
            subject.label != task.instruction
            or subject.partition != task.family
            or subject.digest != subject_ref
            or subject.payload_ref != subject_ref
        ):
            raise ValueError("consistency experiment subject declaration changed")
        for arm_id in ("clean", "inconsistent"):
            repository = _repository_for(task, arm_id, repository_variants)
            expected = {
                "task": task_value,
                "repository": repository,
                "base_subject_ref": subject_ref,
            }
            realization = realizations[(task.id, arm_id)]
            expected_ref = digest_bytes(canonical_json(expected))
            if realization.digest != expected_ref or realization.artifact_ref != expected_ref:
                raise ValueError("consistency experiment realization declaration changed")
            stored_value = json.loads(store.read_bytes(expected_ref))
            if canonical_json(stored_value) != canonical_json(expected):
                raise ValueError("consistency experiment realization content changed")


async def run_consistency_experiment(
    store: ObjectStore,
    *,
    plan_ref: str,
    authorization: str,
    factory: ClientFactory,
    runner: DockerPythonRunner,
    tasks: Sequence[CodingTask],
    repository_variants: Mapping[str, Mapping[str, Mapping[str, str]]] | None,
    profile_validator: Callable[[ClientFactory, PilotSettings], None],
    expected_subjects: int,
    expected_cells: int,
    expected_evaluations: int,
    allow_paid: bool = False,
    export_destination: Path | None = None,
) -> DryExperimentSucceeded | DryExperimentFailed:
    """Execute one independently approved plan and derive two separate reports."""
    manifest_ref: str | None = None
    abstraction_ref: str | None = None
    correctness_ref: str | None = None
    try:
        plan_bytes = store.read_bytes(plan_ref)
        plan = authorize(plan_bytes, authorization)
        if export_destination is not None and export_destination.exists():
            raise ValueError("export destination already exists")
        if not isinstance(plan, ExecutionPlan):
            raise ValueError(
                "the Jig experiment runtime can only execute assay-execution-plan/0.1.0"
            )
        if plan.jig_revision != installed_jig_revision() or plan.assay_version != __version__:
            raise ValueError("installed runtime differs from authorized plan")
        snapshot = StudySnapshot.model_validate_json(store.read_bytes(plan.snapshot_ref))
        verify_snapshot(store, snapshot)
        validate_plan_snapshot(plan, snapshot)
        for arm in snapshot.arms:
            store.publish_json(arm.worker)
        for declaration in snapshot.evaluators:
            store.publish_json(declaration.configuration)
        published_declarations = {
            str(store.publish_json(item.model_dump(mode="json")))
            for item in (*snapshot.arms, *snapshot.evaluators)
        }
        if published_declarations != set(plan.declaration_hashes):
            raise ValueError("published declarations differ from the authorized plan")
        conditions_ref = str(
            store.publish_json(
                [arm.conditions for arm in sorted(snapshot.arms, key=lambda item: item.id)]
            )
        )
        if conditions_ref != plan.execution_conditions_ref:
            raise ValueError("execution conditions differ from the authorized plan")
        reference_closure(store, (plan_ref,))
        if {item.id for item in snapshot.evaluators} != {"abstraction", "correctness"}:
            raise ValueError("DRY experiment evaluator set changed")
        _validate_experiment_shape(
            store,
            snapshot,
            plan,
            tasks=tasks,
            repository_variants=repository_variants,
            expected_subjects=expected_subjects,
            expected_cells=expected_cells,
            expected_evaluations=expected_evaluations,
        )
        settings = PilotSettings.model_validate(snapshot.arms[0].worker["settings"])
        profile_validator(factory, settings)
        if settings.mode == "paid" and not allow_paid:
            raise ValueError("paid consistency experiment requires explicit allow_paid=True")
        worker = ConsistencyWorker(factory, settings, allow_paid=allow_paid)
        structural = StructuralEvaluator()
        correctness = FunctionalCorrectnessEvaluator(runner)
        runtime_evaluators: dict[str, Evaluator] = {
            "abstraction": structural,
            "correctness": correctness,
        }
        if any(
            canonical_json(worker.configuration(arm.id)) != canonical_json(arm.worker)
            for arm in snapshot.arms
        ):
            raise ValueError("worker configuration differs from the authorized plan")
        declared_evaluators = {item.id: item for item in snapshot.evaluators}
        for evaluator_id, evaluator in runtime_evaluators.items():
            if canonical_json(evaluator.configuration()) != canonical_json(
                declared_evaluators[evaluator_id].configuration
            ):
                raise ValueError("evaluator configuration differs from the authorized plan")
        for ref in {cell.realization_ref for cell in plan.cells}:
            rendered = render_input(json.loads(store.read_bytes(ref)), settings.max_input_bytes)
            if isinstance(rendered, WorkerFailure):
                return DryExperimentFailed(rendered.error_type, rendered.message)
        sandbox_check = await runner.run(
            task=tasks[0],
            repository=_repository_for(tasks[0], "clean", repository_variants),
            target_path=tasks[0].target_path,
            source=tasks[0].reused_source,
        )
        if isinstance(sandbox_check, SandboxFailure):
            return DryExperimentFailed(sandbox_check.error_type, sandbox_check.message)
        if sandbox_check.passed != sandbox_check.total:
            return DryExperimentFailed("SandboxSelfTestFailed", "sandbox self-test failed")
        result = await execute_plan(
            plan_bytes=plan_bytes,
            authorization=authorization,
            snapshot=snapshot,
            store=store,
            workers={arm.id: worker for arm in snapshot.arms},
            evaluators=runtime_evaluators,
        )
        if result.manifest_ref is not None:
            manifest_ref = str(result.manifest_ref)
        if isinstance(result, RunFailed):
            return DryExperimentFailed(result.error_type, result.message, manifest_ref)
        assert manifest_ref is not None
        by_evaluator: dict[str, tuple[str, ...]] = {}
        for evaluator_id in ("abstraction", "correctness"):
            selected = tuple(
                sorted(
                    str(result.manifest.evaluation_records[coordinate.id])
                    for coordinate in plan.evaluations
                    if coordinate.evaluator_id == evaluator_id
                )
            )
            by_evaluator[evaluator_id] = selected
        abstraction_ref = str(
            persist_report(
                store,
                _report_config(
                    manifest_ref,
                    by_evaluator["abstraction"],
                    evaluator_id="abstraction",
                    categories=CATEGORIES,
                ),
            )
        )
        correctness_ref = str(
            persist_report(
                store,
                _report_config(
                    manifest_ref,
                    by_evaluator["correctness"],
                    evaluator_id="correctness",
                    categories=CORRECTNESS_CATEGORIES,
                ),
            )
        )
        if export_destination is not None:
            if export_destination.exists():
                raise ValueError("export destination already exists")
            abstraction_bundle = export_bundle(
                store, abstraction_ref, export_destination / "abstraction"
            )
            correctness_bundle = export_bundle(
                store, correctness_ref, export_destination / "correctness"
            )
            for bundle, report_ref in (
                (abstraction_bundle, abstraction_ref),
                (correctness_bundle, correctness_ref),
            ):
                failures = verify_bundle(bundle, report_ref)
                if failures:
                    raise ValueError(f"exported bundle failed verification: {failures}")
        return DryExperimentSucceeded(manifest_ref, abstraction_ref, correctness_ref)
    except Exception as error:
        return DryExperimentFailed(
            type(error).__name__,
            str(error),
            manifest_ref,
            abstraction_ref,
            correctness_ref,
        )


async def run_dry_experiment(
    store: ObjectStore,
    *,
    plan_ref: str,
    authorization: str,
    factory: ClientFactory,
    runner: DockerPythonRunner,
    allow_paid: bool = False,
    export_destination: Path | None = None,
) -> DryExperimentSucceeded | DryExperimentFailed:
    """Execute one independently approved 12-subject DRY plan."""
    return await run_consistency_experiment(
        store,
        plan_ref=plan_ref,
        authorization=authorization,
        factory=factory,
        runner=runner,
        tasks=EXPERIMENT_TASKS,
        repository_variants=None,
        profile_validator=_validate_haiku_profile,
        expected_subjects=12,
        expected_cells=48,
        expected_evaluations=96,
        allow_paid=allow_paid,
        export_destination=export_destination,
    )
