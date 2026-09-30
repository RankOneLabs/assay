"""Prepared, explicitly authorized 12-subject DRY consistency experiment.

The Jig/OpenRouter worker stack this module wires up requires the
``assay[legacy]`` extra. Importing this module never requires Jig; only
calling ``prepare_dry_experiment``/``run_dry_experiment`` does, and a missing
extra fails with an actionable error at that point rather than at import time.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from assay._version import __version__
from assay.canonical import canonical_json
from assay.execution import Evaluator, RunFailed, WorkerFailure, execute_plan
from assay.investigations.chain_fixtures import (
    CHAIN_ARMS,
    CHAIN_STEPS,
    CHAIN_TASKS,
    chain_repository_variants,
)
from assay.investigations.consistency import (
    CATEGORIES,
    EXPERIMENT_TASKS,
    ChainStepEvaluator,
    CodingTask,
    StructuralEvaluator,
    materialize_consistency,
)
from assay.investigations.context_fixtures import CONTEXT_ARMS, context_repository_variants
from assay.investigations.correctness import (
    CORRECTNESS_CATEGORIES,
    DockerPythonRunner,
    FunctionalCorrectnessEvaluator,
    SandboxFailure,
)
from assay.investigations.dose_fixtures import (
    DOSE_ARMS,
    DOSE_TASKS,
    PLACEMENT_ARMS,
    PLACEMENT_LAYOUT,
    dose_repository_variants,
)
from assay.investigations.dry_common import (
    publish_plan_dependencies,
    repository_for,
    validate_experiment_shape,
)
from assay.investigations.layered_fixtures import LAYERED_TASKS, layered_repository_variants
from assay.models import ExecutionPlan, ReportConfig, StatisticalProfile, StudySnapshot
from assay.planning import authorize, compile_plan, validate_plan_snapshot
from assay.report_engine import persist_report
from assay.store import ObjectStore
from assay.verify import export_bundle, reference_closure, verify_bundle, verify_snapshot
from consistency_pilot.pilot import installed_jig_revision

if TYPE_CHECKING:
    from assay.adapters.consistency import ClientFactory, ConsistencyWorker, PilotSettings
    from assay.adapters.openrouter_policy import OpenRouterSettings


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
    correctness_report_ref: str | None
    # Every report by evaluator id; chained runs have one abstraction report per step.
    report_refs: dict[str, str] | None = None


def _import_legacy_worker_stack() -> tuple[type[ConsistencyWorker], type[PilotSettings], Any]:
    try:
        from assay.adapters.consistency import ConsistencyWorker, PilotSettings, render_input
    except ModuleNotFoundError as error:
        from assay.adapters import missing_legacy_extra

        raise missing_legacy_extra("consistency_pilot.dry_experiment", error) from error
    return ConsistencyWorker, PilotSettings, render_input


SCENARIOS = ("v1", "layered", "dose", "placement", "chain", "context")


@dataclass(frozen=True)
class DryScenario:
    """A twelve-subject population, its arms, and how its report compares them."""

    tasks: tuple[CodingTask, ...]
    repository_variants: dict[str, dict[str, dict[str, str]]] | None
    arm_ids: tuple[str, ...] = ("clean", "inconsistent")
    schedule: str = "subject-counterbalanced-v1"
    reference_arm: str = "inconsistent"
    candidates: tuple[str, ...] = ("clean",)
    # Successive additions per cell; 0 means one ordinary call per cell.
    chain_steps: int = 0

    @property
    def cells(self) -> int:
        return len(self.tasks) * len(self.arm_ids) * 2

    @property
    def requests(self) -> int:
        return self.cells * max(1, self.chain_steps)

    @property
    def evaluator_ids(self) -> tuple[str, ...]:
        if self.chain_steps:
            return tuple(f"abstraction-{step}" for step in range(1, self.chain_steps + 1))
        return ("abstraction", "correctness")

    @property
    def evaluations(self) -> int:
        return self.cells * len(self.evaluator_ids)

    @property
    def request_basis(self) -> str:
        if self.chain_steps:
            return f"{self.cells} cells of {self.chain_steps} one-call steps"
        return f"{self.cells} one-call cells"


def dry_scenario(scenario: str) -> DryScenario:
    """The named scenario set: v1 single-file, layered two-arm, or dose-response."""
    if scenario == "v1":
        return DryScenario(EXPERIMENT_TASKS, None)
    if scenario == "layered":
        return DryScenario(LAYERED_TASKS, layered_repository_variants())
    if scenario == "dose":
        # Every mess level is compared against the fully consistent file.
        return DryScenario(
            DOSE_TASKS,
            dose_repository_variants(),
            arm_ids=DOSE_ARMS,
            schedule="subject-rotated-v1",
            reference_arm=DOSE_ARMS[0],
            candidates=DOSE_ARMS[1:],
        )
    if scenario == "placement":
        # The inline callers sit right above the model's insertion point.
        return DryScenario(
            DOSE_TASKS,
            dose_repository_variants(PLACEMENT_LAYOUT),
            arm_ids=PLACEMENT_ARMS,
            schedule="subject-rotated-v1",
            reference_arm="mess-00",
            candidates=PLACEMENT_ARMS[1:],
        )
    if scenario == "chain":
        # Five successive additions per cell, starting from placement files.
        return DryScenario(
            CHAIN_TASKS,
            chain_repository_variants(),
            arm_ids=CHAIN_ARMS,
            schedule="subject-rotated-v1",
            reference_arm=CHAIN_ARMS[0],
            candidates=CHAIN_ARMS[1:],
            chain_steps=CHAIN_STEPS,
        )
    if scenario == "context":
        # The same tail-07 file in repositories padded to about 30 KB and 90 KB.
        return DryScenario(
            DOSE_TASKS,
            context_repository_variants(),
            arm_ids=CONTEXT_ARMS,
            schedule="subject-rotated-v1",
            reference_arm=CONTEXT_ARMS[0],
            candidates=CONTEXT_ARMS[1:],
        )
    raise ValueError(f"unknown DRY scenario set {scenario!r}; expected one of {SCENARIOS}")


def _prompt_override(scenario: str) -> dict[str, Any]:
    if scenario == "v1":
        return {}
    dry_scenario(scenario)
    from assay.adapters.consistency import LAYERED_SYSTEM_PROMPT

    override: dict[str, Any] = {"system_prompt": LAYERED_SYSTEM_PROMPT}
    if scenario == "context":
        # Padded repositories render to about 103 KB of prompt.
        override["max_input_bytes"] = 131_072
    return override


def haiku_dry_settings(scenario: str = "v1") -> PilotSettings:
    """One call per cell at $0.06 each; 48 cells ($2.88) for two-arm sets."""
    _, PilotSettings, _ = _import_legacy_worker_stack()
    population = dry_scenario(scenario)
    return PilotSettings(
        **_prompt_override(scenario),
        mode="paid",
        max_llm_calls=1,
        max_total_requests=population.requests,
        max_spend_usd=Decimal("0.06") * population.requests,
        request_cost_bound_usd=Decimal("0.06"),
        pricing_basis=(
            "OpenRouter inline usage.cost (USD credits), Claude 3 Haiku via "
            "Amazon Bedrock; 2026-09-11 rate caps $0.25/$1.25 per million "
            f"input/output tokens; {population.request_basis}; no per-request fee; bound "
            "assumes <=200000 input and <=2048 output tokens, no BYOK, paid "
            "plugins, or additional charges; operator must validate before execution"
        ),
    )


def frontier_dry_settings(
    model: str, scenario: str = "v1", request_timeout_s: float = 120
) -> PilotSettings:
    """One call per cell at $0.25 each; 48 cells ($12) for two-arm sets.

    The per-request bound covers a full 65,536-byte request body (<=65,536
    input tokens) at $2.20/M plus 8,192 output tokens at $12/M. Temperature is
    omitted because these routes reject or ignore it for reasoning models.
    """
    _, PilotSettings, _ = _import_legacy_worker_stack()
    population = dry_scenario(scenario)
    return PilotSettings(
        **_prompt_override(scenario),
        mode="paid",
        temperature=None,
        max_output_tokens=8192,
        max_llm_calls=1,
        max_total_requests=population.requests,
        request_timeout_s=request_timeout_s,
        attempt_timeout_s=request_timeout_s + 60,
        max_spend_usd=Decimal("0.25") * population.requests,
        request_cost_bound_usd=Decimal("0.25"),
        pricing_basis=(
            f"OpenRouter inline usage.cost (USD credits), {model}; 2026-09-30 rate "
            f"caps <=$2.20/<=$12 per million input/output tokens; {population.request_basis}; "
            "bound assumes <=65536 input and <=8192 output tokens"
        ),
    )


def dry_profiles(scenario: str = "v1") -> dict[str, tuple[OpenRouterSettings, PilotSettings]]:
    """Governed DRY routes by name: provider route and worker settings."""
    from assay.adapters.openrouter import (
        GEMINI_3_1_PRO_VERTEX,
        GPT_6_1_SOL_AZURE,
        HAIKU_4_5_BEDROCK,
        HAIKU_BEDROCK,
        SONNET_5_5_BEDROCK,
    )

    profiles = {"haiku": (HAIKU_BEDROCK, haiku_dry_settings(scenario))}
    for name, route in (
        ("sonnet-5.5", SONNET_5_5_BEDROCK),
        ("haiku-4.5", HAIKU_4_5_BEDROCK),
        ("gpt-6.1-sol", GPT_6_1_SOL_AZURE),
        ("gemini-3.1-pro", GEMINI_3_1_PRO_VERTEX),
    ):
        profiles[name] = (
            route,
            frontier_dry_settings(route.model, scenario, request_timeout_s=route.timeout_s),
        )
    return profiles


def _validate_dry_profile(
    factory: ClientFactory, settings: PilotSettings, scenario: str = "v1"
) -> None:
    from assay.adapters.openrouter import OpenRouterFactory

    provider = canonical_json(factory.configuration())
    for route, governed in dry_profiles(scenario).values():
        if canonical_json(OpenRouterFactory(route).configuration()) == provider:
            if settings != governed:
                raise ValueError("DRY experiment settings differ from the governed profile")
            return
    raise ValueError("DRY experiment provider is not a governed DRY profile")


def prepare_dry_experiment(
    store: ObjectStore,
    *,
    factory: ClientFactory,
    settings: PilotSettings,
    schemas: Mapping[str, dict[str, object]],
    runner: DockerPythonRunner,
    scenario: str = "v1",
) -> DryExperimentPrepared | DryExperimentFailed:
    """Materialize the full study without clients, containers, or provider calls."""
    try:
        population = dry_scenario(scenario)
        if len(population.tasks) < 10:
            raise ValueError("DRY experiment requires at least ten subjects")
        _validate_dry_profile(factory, settings, scenario)
        ConsistencyWorker, _, _ = _import_legacy_worker_stack()
        worker = _scenario_worker(ConsistencyWorker(factory, settings), population)
        evaluators = _scenario_evaluators(population, runner)
        snapshot = materialize_consistency(
            store,
            worker_configuration=worker.configuration(population.arm_ids[0]),
            evaluator=StructuralEvaluator(),
            correctness_evaluator=evaluators.get("correctness"),
            abstraction_evaluators={
                key: value for key, value in evaluators.items() if key != "correctness"
            },
            schemas=schemas,
            tasks=population.tasks,
            evaluator_repeats=1,
            execution_schedule=population.schedule,
            repository_variants=population.repository_variants,
            arm_ids=population.arm_ids,
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
        if len(plan.cells) != population.cells or len(plan.evaluations) != population.evaluations:
            raise ValueError("unexpected DRY experiment grid")
        return DryExperimentPrepared(snapshot_ref, plan_ref, len(plan.cells), len(plan.evaluations))
    except Exception as error:
        return DryExperimentFailed(type(error).__name__, str(error))


def _scenario_worker(inner: ConsistencyWorker, population: DryScenario) -> Any:
    if not population.chain_steps:
        return inner
    from assay.adapters.consistency import ChainWorker

    return ChainWorker(inner)


def _scenario_evaluators(population: DryScenario, runner: DockerPythonRunner) -> dict[str, Any]:
    if population.chain_steps:
        return {
            evaluator_id: ChainStepEvaluator(step)
            for step, evaluator_id in enumerate(population.evaluator_ids)
        }
    return {
        "abstraction": StructuralEvaluator(),
        "correctness": FunctionalCorrectnessEvaluator(runner),
    }


def _report_config(
    manifest_ref: str,
    record_refs: tuple[str, ...],
    *,
    evaluator_id: str,
    categories: tuple[str, ...],
    reference_arm: str = "inconsistent",
    candidates: tuple[str, ...] = ("clean",),
) -> ReportConfig:
    return ReportConfig(
        manifest_refs=(manifest_ref,),
        record_refs=record_refs,
        reference_arm=reference_arm,
        candidates=candidates,
        evaluator_id=evaluator_id,
        metric="ordinal",
        categories=categories,
        evaluator_repeat_aggregation="median",
        worker_repeat_aggregation="median",
        statistical_profile=StatisticalProfile(seed=7, bootstrap_samples=10_000),
        engine_version=__version__,
    )


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
    arm_ids: tuple[str, ...] = ("clean", "inconsistent"),
    schedule: str = "subject-counterbalanced-v1",
    reference_arm: str = "inconsistent",
    candidates: tuple[str, ...] = ("clean",),
    population: DryScenario | None = None,
) -> DryExperimentSucceeded | DryExperimentFailed:
    """Execute one independently approved plan and derive one report per evaluator."""
    manifest_ref: str | None = None
    abstraction_ref: str | None = None
    correctness_ref: str | None = None
    if population is None:
        population = DryScenario(tuple(tasks), None)
    try:
        plan_bytes = store.read_bytes(plan_ref)
        plan = authorize(plan_bytes, authorization)
        if export_destination is not None and export_destination.exists():
            raise ValueError("export destination already exists")
        if not isinstance(plan, ExecutionPlan):
            raise ValueError(
                "the Jig experiment runtime can only execute assay-execution-plan/0.1.0"
            )
        ConsistencyWorker, PilotSettings, render_input = _import_legacy_worker_stack()
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
        if {item.id for item in snapshot.evaluators} != set(population.evaluator_ids):
            raise ValueError("DRY experiment evaluator set changed")
        validate_experiment_shape(
            store,
            snapshot,
            plan,
            tasks=tasks,
            repository_variants=repository_variants,
            expected_subjects=expected_subjects,
            expected_cells=expected_cells,
            expected_evaluations=expected_evaluations,
            arm_ids=arm_ids,
            schedule=schedule,
        )
        settings = PilotSettings.model_validate(snapshot.arms[0].worker["settings"])
        profile_validator(factory, settings)
        if settings.mode == "paid" and not allow_paid:
            raise ValueError("paid consistency experiment requires explicit allow_paid=True")
        worker = _scenario_worker(
            ConsistencyWorker(factory, settings, allow_paid=allow_paid), population
        )
        runtime_evaluators: dict[str, Evaluator] = _scenario_evaluators(population, runner)
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
        if "correctness" in runtime_evaluators:
            sandbox_check = await runner.run(
                task=tasks[0],
                repository=repository_for(tasks[0], arm_ids[0], repository_variants),
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
        report_refs: dict[str, str] = {}
        for evaluator_id in population.evaluator_ids:
            selected = tuple(
                sorted(
                    str(result.manifest.evaluation_records[coordinate.id])
                    for coordinate in plan.evaluations
                    if coordinate.evaluator_id == evaluator_id
                )
            )
            report_refs[evaluator_id] = str(
                persist_report(
                    store,
                    _report_config(
                        manifest_ref,
                        selected,
                        evaluator_id=evaluator_id,
                        categories=(
                            CORRECTNESS_CATEGORIES if evaluator_id == "correctness" else CATEGORIES
                        ),
                        reference_arm=reference_arm,
                        candidates=candidates,
                    ),
                )
            )
        abstraction_ref = report_refs.get("abstraction", report_refs[population.evaluator_ids[0]])
        correctness_ref = report_refs.get("correctness")
        if export_destination is not None:
            if export_destination.exists():
                raise ValueError("export destination already exists")
            for evaluator_id, report_ref in report_refs.items():
                bundle = export_bundle(store, report_ref, export_destination / evaluator_id)
                failures = verify_bundle(bundle, report_ref)
                if failures:
                    raise ValueError(f"exported bundle failed verification: {failures}")
        return DryExperimentSucceeded(manifest_ref, abstraction_ref, correctness_ref, report_refs)
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
    scenario: str = "v1",
) -> DryExperimentSucceeded | DryExperimentFailed:
    """Execute one independently approved 12-subject DRY plan."""
    try:
        population = dry_scenario(scenario)
    except ValueError as error:
        return DryExperimentFailed(type(error).__name__, str(error))

    def validate_profile(factory: ClientFactory, settings: PilotSettings) -> None:
        _validate_dry_profile(factory, settings, scenario)

    return await run_consistency_experiment(
        store,
        plan_ref=plan_ref,
        authorization=authorization,
        factory=factory,
        runner=runner,
        tasks=population.tasks,
        repository_variants=population.repository_variants,
        profile_validator=validate_profile,
        expected_subjects=12,
        expected_cells=population.cells,
        expected_evaluations=population.evaluations,
        allow_paid=allow_paid,
        export_destination=export_destination,
        arm_ids=population.arm_ids,
        schedule=population.schedule,
        reference_arm=population.reference_arm,
        candidates=population.candidates,
        population=population,
    )
