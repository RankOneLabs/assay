"""Governed four-repository qualification pilot for realistic context handling.

The Jig/OpenRouter worker stack this module wires up requires the
``assay[legacy]`` extra. Importing this module never requires Jig; only
calling the ``prepare_*``/``run_*`` entry points does, and a missing extra
fails with an actionable error at that point rather than at import time.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from assay.canonical import canonical_json
from assay.investigations.consistency import (
    CodingTask,
    StructuralEvaluator,
    materialize_consistency,
)
from assay.investigations.correctness import DockerPythonRunner, FunctionalCorrectnessEvaluator
from assay.investigations.dry_common import publish_plan_dependencies
from assay.investigations.dry_experiment import (
    DryExperimentFailed,
    DryExperimentPrepared,
    DryExperimentSucceeded,
    run_consistency_experiment,
)
from assay.investigations.pilot import installed_jig_revision
from assay.investigations.realistic_fixtures import (
    REALISTIC_PILOT_FIXTURES,
    REALISTIC_PILOT_TASKS,
    RepositoryFixture,
    realistic_repository_variants,
    validate_repository_fixture,
)
from assay.models import PriceEstimate
from assay.planning import compile_plan
from assay.store import ObjectStore
from assay.verify import reference_closure, verify_snapshot

if TYPE_CHECKING:
    from assay.adapters.consistency import ClientFactory, ConsistencyWorker, PilotSettings


def _import_legacy_worker_stack() -> tuple[type[ConsistencyWorker], type[PilotSettings], Any]:
    try:
        from assay.adapters.consistency import ConsistencyWorker, PilotSettings, render_input
    except ModuleNotFoundError as error:
        from assay.adapters import missing_legacy_extra

        raise missing_legacy_extra("assay.investigations.realistic_pilot", error) from error
    return ConsistencyWorker, PilotSettings, render_input


def realistic_haiku_settings() -> PilotSettings:
    """Sixteen one-call cells with room for the generated 1,225-line repositories."""
    _, PilotSettings, _ = _import_legacy_worker_stack()
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


def realistic_gpt_oss_smoke_settings() -> PilotSettings:
    """Four one-call cells for a low-cost end-to-end repository smoke run."""
    _, PilotSettings, _ = _import_legacy_worker_stack()
    return PilotSettings(
        mode="paid",
        max_input_bytes=64_000,
        max_llm_calls=1,
        max_total_requests=4,
        max_spend_usd=Decimal("0.02"),
        request_cost_bound_usd=Decimal("0.005"),
        pricing_basis=(
            "OpenRouter inline usage.cost (USD credits), GPT-OSS 120B via "
            "CoreWeave fp4; 2026-09-11 rate caps $0.03/$0.17 per "
            "million input/output tokens; 4 one-call cells; no per-request fee; "
            "bound assumes <=65536 input and <=2048 output tokens, no BYOK, paid "
            "plugins, or additional charges; operator must validate before execution"
        ),
    )


def _validate_realistic_profile(factory: ClientFactory, settings: PilotSettings) -> None:
    from assay.adapters.openrouter import HAIKU_BEDROCK, OpenRouterFactory

    if settings != realistic_haiku_settings():
        raise ValueError("realistic pilot settings differ from the governed Haiku profile")
    if canonical_json(factory.configuration()) != canonical_json(
        OpenRouterFactory(HAIKU_BEDROCK).configuration()
    ):
        raise ValueError("realistic pilot provider differs from the governed Haiku profile")


def _validate_realistic_smoke_profile(factory: ClientFactory, settings: PilotSettings) -> None:
    from assay.adapters.openrouter import GPT_OSS_120B_COREWEAVE, OpenRouterFactory

    if settings != realistic_gpt_oss_smoke_settings():
        raise ValueError("realistic smoke settings differ from the governed GPT-OSS profile")
    if canonical_json(factory.configuration()) != canonical_json(
        OpenRouterFactory(GPT_OSS_120B_COREWEAVE).configuration()
    ):
        raise ValueError("realistic smoke provider differs from the governed GPT-OSS profile")


REALISTIC_SMOKE_FIXTURES = tuple(
    fixture for fixture in REALISTIC_PILOT_FIXTURES if fixture.id == "commerce-sku"
)
if len(REALISTIC_SMOKE_FIXTURES) != 1:
    raise RuntimeError("realistic smoke fixture selection changed")
REALISTIC_SMOKE_TASKS = tuple(fixture.task for fixture in REALISTIC_SMOKE_FIXTURES)


def _variants_for(
    fixtures: Sequence[RepositoryFixture],
) -> dict[str, dict[str, Mapping[str, str]]]:
    return {
        fixture.task.id: {
            "clean": fixture.clean_repository,
            "inconsistent": fixture.inconsistent_repository,
        }
        for fixture in fixtures
    }


def _prepare_realistic(
    store: ObjectStore,
    *,
    factory: ClientFactory,
    settings: PilotSettings,
    schemas: Mapping[str, dict[str, object]],
    runner: DockerPythonRunner,
    fixtures: Sequence[RepositoryFixture],
    tasks: Sequence[CodingTask],
    repository_variants: Mapping[str, Mapping[str, Mapping[str, str]]],
    profile_validator: Callable[[ClientFactory, PilotSettings], None],
    expected_cells: int,
    expected_evaluations: int,
) -> DryExperimentPrepared | DryExperimentFailed:
    try:
        profile_validator(factory, settings)
        for fixture in fixtures:
            validate_repository_fixture(fixture)
        ConsistencyWorker, _, _ = _import_legacy_worker_stack()
        worker = ConsistencyWorker(factory, settings)
        snapshot = materialize_consistency(
            store,
            worker_configuration=worker.configuration("clean"),
            evaluator=StructuralEvaluator(),
            correctness_evaluator=FunctionalCorrectnessEvaluator(runner),
            schemas=schemas,
            tasks=tasks,
            evaluator_repeats=1,
            execution_schedule="subject-counterbalanced-v1",
            repository_variants=repository_variants,
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
            arm_cost_estimates={
                arm_id: PriceEstimate(
                    amount=float(
                        settings.request_cost_bound_usd * len(fixtures) * 2
                    ),
                    currency="USD",
                    coverage="estimated",
                )
                for arm_id in ("clean", "inconsistent")
            },
        )
        plan_ref = str(store.publish_json(plan.model_dump(mode="json")))
        reference_closure(store, (plan_ref,))
        if len(plan.cells) != expected_cells or len(plan.evaluations) != expected_evaluations:
            raise ValueError("unexpected realistic experiment grid")
        return DryExperimentPrepared(snapshot_ref, plan_ref, expected_cells, expected_evaluations)
    except Exception as error:
        return DryExperimentFailed(type(error).__name__, str(error))


def prepare_realistic_pilot(
    store: ObjectStore,
    *,
    factory: ClientFactory,
    settings: PilotSettings,
    schemas: Mapping[str, dict[str, object]],
    runner: DockerPythonRunner,
) -> DryExperimentPrepared | DryExperimentFailed:
    """Materialize the qualification pilot without clients, containers, or provider calls."""
    return _prepare_realistic(
        store,
        factory=factory,
        settings=settings,
        schemas=schemas,
        runner=runner,
        fixtures=REALISTIC_PILOT_FIXTURES,
        tasks=REALISTIC_PILOT_TASKS,
        repository_variants=realistic_repository_variants(),
        profile_validator=_validate_realistic_profile,
        expected_cells=16,
        expected_evaluations=32,
    )


def prepare_realistic_smoke(
    store: ObjectStore,
    *,
    factory: ClientFactory,
    settings: PilotSettings,
    schemas: Mapping[str, dict[str, object]],
    runner: DockerPythonRunner,
) -> DryExperimentPrepared | DryExperimentFailed:
    """Materialize the GPT-OSS smoke run without clients, containers, or provider calls."""
    return _prepare_realistic(
        store,
        factory=factory,
        settings=settings,
        schemas=schemas,
        runner=runner,
        fixtures=REALISTIC_SMOKE_FIXTURES,
        tasks=REALISTIC_SMOKE_TASKS,
        repository_variants=_variants_for(REALISTIC_SMOKE_FIXTURES),
        profile_validator=_validate_realistic_smoke_profile,
        expected_cells=4,
        expected_evaluations=8,
    )


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


async def run_realistic_smoke(
    store: ObjectStore,
    *,
    plan_ref: str,
    authorization: str,
    factory: ClientFactory,
    runner: DockerPythonRunner,
    allow_paid: bool = False,
    export_destination: Path | None = None,
) -> DryExperimentSucceeded | DryExperimentFailed:
    """Execute one independently inspected and approved GPT-OSS repository smoke plan."""
    return await run_consistency_experiment(
        store,
        plan_ref=plan_ref,
        authorization=authorization,
        factory=factory,
        runner=runner,
        tasks=REALISTIC_SMOKE_TASKS,
        repository_variants=_variants_for(REALISTIC_SMOKE_FIXTURES),
        profile_validator=_validate_realistic_smoke_profile,
        expected_subjects=1,
        expected_cells=4,
        expected_evaluations=8,
        allow_paid=allow_paid,
        export_destination=export_destination,
    )
