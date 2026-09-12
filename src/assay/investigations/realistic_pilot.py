"""Governed four-repository qualification pilot for realistic context handling."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

from assay.adapters.consistency import ClientFactory, ConsistencyWorker, PilotSettings
from assay.adapters.openrouter import HAIKU_BEDROCK, OpenRouterFactory
from assay.canonical import canonical_json
from assay.investigations.consistency import StructuralEvaluator, materialize_consistency
from assay.investigations.correctness import DockerPythonRunner, FunctionalCorrectnessEvaluator
from assay.investigations.dry_experiment import (
    DryExperimentFailed,
    DryExperimentPrepared,
    DryExperimentSucceeded,
    publish_plan_dependencies,
    run_consistency_experiment,
)
from assay.investigations.pilot import installed_jig_revision
from assay.investigations.realistic_fixtures import (
    REALISTIC_PILOT_FIXTURES,
    REALISTIC_PILOT_TASKS,
    realistic_repository_variants,
    validate_repository_fixture,
)
from assay.planning import compile_plan
from assay.store import ObjectStore
from assay.verify import reference_closure, verify_snapshot


def realistic_haiku_settings() -> PilotSettings:
    """Sixteen one-call cells with room for the generated 1,225-line repositories."""
    return PilotSettings(
        mode="paid",
        max_input_bytes=64_000,
        max_llm_calls=1,
        max_total_requests=16,
        max_spend_usd=Decimal("0.96"),
        request_cost_bound_usd=Decimal("0.06"),
        pricing_basis=(
            "OpenRouter inline usage.cost (USD credits), Claude 3 Haiku via "
            "Amazon Bedrock; 2026-09-11 rate caps $0.25/$1.25 per million "
            "input/output tokens; 16 one-call cells; no per-request fee; bound "
            "assumes <=200000 input and <=2048 output tokens, no BYOK, paid "
            "plugins, or additional charges; operator must validate before execution"
        ),
    )


def _validate_realistic_profile(factory: ClientFactory, settings: PilotSettings) -> None:
    if settings != realistic_haiku_settings():
        raise ValueError("realistic pilot settings differ from the governed Haiku profile")
    if canonical_json(factory.configuration()) != canonical_json(
        OpenRouterFactory(HAIKU_BEDROCK).configuration()
    ):
        raise ValueError("realistic pilot provider differs from the governed Haiku profile")


def prepare_realistic_pilot(
    store: ObjectStore,
    *,
    factory: ClientFactory,
    settings: PilotSettings,
    schemas: Mapping[str, dict[str, object]],
    runner: DockerPythonRunner,
) -> DryExperimentPrepared | DryExperimentFailed:
    """Materialize the qualification pilot without clients, containers, or provider calls."""
    try:
        _validate_realistic_profile(factory, settings)
        for fixture in REALISTIC_PILOT_FIXTURES:
            validate_repository_fixture(fixture)
        worker = ConsistencyWorker(factory, settings)
        snapshot = materialize_consistency(
            store,
            worker_configuration=worker.configuration("clean"),
            evaluator=StructuralEvaluator(),
            correctness_evaluator=FunctionalCorrectnessEvaluator(runner),
            schemas=schemas,
            tasks=REALISTIC_PILOT_TASKS,
            evaluator_repeats=1,
            execution_schedule="subject-counterbalanced-v1",
            repository_variants=realistic_repository_variants(),
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
        if len(plan.cells) != 16 or len(plan.evaluations) != 32:
            raise ValueError("unexpected realistic qualification grid")
        return DryExperimentPrepared(snapshot_ref, plan_ref, 16, 32)
    except Exception as error:
        return DryExperimentFailed(type(error).__name__, str(error))


async def run_realistic_pilot(
    store: ObjectStore,
    *,
    plan_ref: str,
    authorization: str,
    factory: ClientFactory,
    runner: DockerPythonRunner,
    allow_paid: bool = False,
    export_destination: Path | None = None,
) -> DryExperimentSucceeded | DryExperimentFailed:
    """Execute one independently inspected and approved realistic pilot plan."""
    return await run_consistency_experiment(
        store,
        plan_ref=plan_ref,
        authorization=authorization,
        factory=factory,
        runner=runner,
        tasks=REALISTIC_PILOT_TASKS,
        repository_variants=realistic_repository_variants(),
        profile_validator=_validate_realistic_profile,
        expected_subjects=4,
        expected_cells=16,
        expected_evaluations=32,
        allow_paid=allow_paid,
        export_destination=export_destination,
    )
