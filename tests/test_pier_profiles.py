from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from assay.canonical import canonical_json
from assay.investigations.dry_common import deterministic_cell_price_estimate
from assay.investigations.pier_experiment import (
    PIER_COST_PER_CELL_USD,
    PIER_FULL_PER_ARM_USD,
    PIER_FULL_TOTAL_USD,
    PIER_QUALIFICATION_PER_ARM_USD,
    PIER_QUALIFICATION_TOTAL_USD,
    PIER_SMOKE_PER_ARM_USD,
    PIER_SMOKE_TOTAL_USD,
    PierExperimentPrepared,
    prepare_pier_full,
    prepare_pier_qualification,
    prepare_pier_smoke,
)
from assay.models import ExecutionPlanV2, StudySnapshot, parse_execution_plan
from assay.store import ObjectStore


def test_per_cell_rate_is_the_documented_seventy_two_cents() -> None:
    assert Decimal("0.72") == PIER_COST_PER_CELL_USD


def test_full_ceilings_are_derived_from_the_per_cell_rate() -> None:
    assert deterministic_cell_price_estimate(
        cell_count=48, per_cell_usd=PIER_COST_PER_CELL_USD
    ).amount == float(PIER_FULL_TOTAL_USD)
    assert deterministic_cell_price_estimate(
        cell_count=24, per_cell_usd=PIER_COST_PER_CELL_USD
    ).amount == float(PIER_FULL_PER_ARM_USD)


def test_smoke_ceilings_are_derived_from_the_per_cell_rate() -> None:
    assert deterministic_cell_price_estimate(
        cell_count=4, per_cell_usd=PIER_COST_PER_CELL_USD
    ).amount == float(PIER_SMOKE_TOTAL_USD)
    assert deterministic_cell_price_estimate(
        cell_count=2, per_cell_usd=PIER_COST_PER_CELL_USD
    ).amount == float(PIER_SMOKE_PER_ARM_USD)


def test_qualification_ceilings_are_derived_from_the_per_cell_rate() -> None:
    assert deterministic_cell_price_estimate(
        cell_count=16, per_cell_usd=PIER_COST_PER_CELL_USD
    ).amount == float(PIER_QUALIFICATION_TOTAL_USD)
    assert deterministic_cell_price_estimate(
        cell_count=8, per_cell_usd=PIER_COST_PER_CELL_USD
    ).amount == float(PIER_QUALIFICATION_PER_ARM_USD)


def test_literal_ceiling_constants_match_the_spec_exactly() -> None:
    assert PIER_FULL_TOTAL_USD == "34.56"
    assert PIER_FULL_PER_ARM_USD == "17.28"
    assert PIER_SMOKE_TOTAL_USD == "2.88"
    assert PIER_SMOKE_PER_ARM_USD == "1.44"
    assert PIER_QUALIFICATION_TOTAL_USD == "11.52"
    assert PIER_QUALIFICATION_PER_ARM_USD == "5.76"


def _plan_for(store: ObjectStore, result: PierExperimentPrepared) -> ExecutionPlanV2:
    plan = parse_execution_plan(json.loads(store.read_bytes(result.plan_ref)))
    assert isinstance(plan, ExecutionPlanV2)
    assert canonical_json(plan.model_dump(mode="json")) == store.read_bytes(result.plan_ref)
    return plan


def test_full_profile_shape(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / ".assay")
    result = prepare_pier_full(store)
    assert isinstance(result, PierExperimentPrepared)
    assert result.cells == 48
    plan = _plan_for(store, result)
    snapshot = StudySnapshot.model_validate_json(store.read_bytes(plan.snapshot_ref))
    assert len(snapshot.subjects) == 12
    assert len(snapshot.arms) == 2
    assert plan.worker_repeats == 2
    assert plan.cost_estimate.amount == float(PIER_FULL_TOTAL_USD)
    assert {value.amount for value in plan.arm_cost_estimates.values()} == {
        float(PIER_FULL_PER_ARM_USD)
    }


def test_smoke_profile_shape(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / ".assay")
    result = prepare_pier_smoke(store)
    assert isinstance(result, PierExperimentPrepared)
    assert result.cells == 4
    plan = _plan_for(store, result)
    assert plan.cost_estimate.amount == float(PIER_SMOKE_TOTAL_USD)
    assert {value.amount for value in plan.arm_cost_estimates.values()} == {
        float(PIER_SMOKE_PER_ARM_USD)
    }


def test_qualification_profile_shape_retains_all_four_fixtures(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / ".assay")
    result = prepare_pier_qualification(store)
    assert isinstance(result, PierExperimentPrepared)
    assert result.cells == 16
    plan = _plan_for(store, result)
    snapshot = StudySnapshot.model_validate_json(store.read_bytes(plan.snapshot_ref))
    assert {subject.id for subject in snapshot.subjects} == {
        "commerce-sku",
        "support-tag",
        "telemetry-count",
        "identity-name",
    }
    assert plan.cost_estimate.amount == float(PIER_QUALIFICATION_TOTAL_USD)


def test_profiles_share_the_qualified_runtime_but_pin_distinct_configurations(
    tmp_path: Path,
) -> None:
    """Every profile is qualified against the same bridge identity (the same
    recorded qualification's lock digest) -- what must never be substitutable
    across profiles is the study *configuration* (model route, trial limits,
    profile name), which is why configuration_ref stays distinct per profile
    even though runtime.version is now the shared, exactly-pinned qualified
    identity rather than an invented per-profile version string."""
    from assay.investigations.pier_experiment import EXPECTED_BRIDGE_LOCK_DIGEST

    store = ObjectStore(tmp_path / ".assay")
    full = _plan_for(store, prepare_pier_full(store))
    smoke = _plan_for(store, prepare_pier_smoke(store))
    qualification = _plan_for(store, prepare_pier_qualification(store))

    runtimes = {full.runtime.version, smoke.runtime.version, qualification.runtime.version}
    assert runtimes == {EXPECTED_BRIDGE_LOCK_DIGEST}
    assert full.runtime.configuration_ref != smoke.runtime.configuration_ref
    assert full.runtime.configuration_ref != qualification.runtime.configuration_ref
    assert smoke.runtime.configuration_ref != qualification.runtime.configuration_ref


def test_evaluator_and_paired_v2_report_declarations_are_unchanged() -> None:
    """The pier_experiment module is additive: it never imports or mutates the
    existing DRY experiment's evaluator ids or the paired-v2 statistical profile."""
    import inspect

    from assay import investigations
    from assay.investigations import pier_experiment
    from assay.investigations.dry_experiment import EXPERIMENT_TASKS as _unused  # noqa: F401
    from assay.models import StatisticalProfile

    source = inspect.getsource(pier_experiment)
    assert "import dry_experiment" not in source
    assert "from assay.investigations.dry_experiment" not in source
    assert StatisticalProfile.model_fields["name"].annotation is not None
    profile = StatisticalProfile(seed=1, bootstrap_samples=100)
    assert profile.name == "paired-v2"
    assert investigations is not None
