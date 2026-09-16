"""End-to-end 0.2.0 runtime closure enforcement and cross-profile report isolation.

These exercise the discriminator-aware reference closure walk (manifests, execution
outcomes, evaluation failures, and evidence all reach a v2 plan's ``runtime`` binding,
not just a directly-parsed plan), a store-aware boundary that rejects a missing runtime
closure before execution and before reporting, and the report engine's fingerprint
isolation across legacy, same-profile, and cross-profile v2 runs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_execution import default_runtime, execution_fixture

from assay.execution import RunSucceeded, execute_plan
from assay.models import ReportConfig, StatisticalProfile, parse_execution_plan
from assay.planning import require_runtime_closure
from assay.references import reference_closure
from assay.report_engine import ReportError, build_report
from assay.store import ObjectStore
from assay.verify import export_bundle, verify_bundle, verify_manifest


def _report_config(*results: RunSucceeded, **updates: object) -> ReportConfig:
    return ReportConfig(
        manifest_refs=tuple(str(result.manifest_ref) for result in results),
        record_refs=tuple(
            ref for result in results for ref in result.manifest.evaluation_records.values()
        ),
        reference_arm="reference",
        candidates=("candidate",),
        evaluator_id="quality",
        metric="scalar",
        scalar_direction="higher_is_better",
        evaluator_repeat_aggregation="mean",
        worker_repeat_aggregation="mean",
        statistical_profile=StatisticalProfile(seed=9, bootstrap_samples=1000),
        engine_version="0.1.0",
    ).model_copy(update=updates)


async def test_manifest_rooted_closure_requires_the_v2_runtime_object(tmp_path: Path) -> None:
    """A manifest/outcome/evidence-rooted walk must reach ``runtime.configuration_ref``.

    Before the discriminator-aware fix, ``_PATHS["assay-run-manifest/0.1.0"]["plan_ref"]``
    was hardcoded to the 0.1.0 path set, so a v2 plan reached via a manifest (rather than
    parsed directly) silently dropped its runtime edge -- this regresses that gap.
    """
    store = ObjectStore(tmp_path)
    runtime = default_runtime(store)
    fixture = execution_fixture(store, subject_ids=("ok",), worker_repeats=1, runtime=runtime)
    result = await execute_plan(**fixture.arguments)
    assert isinstance(result, RunSucceeded), result
    manifest_ref = str(result.manifest_ref)

    assert verify_manifest(store, manifest_ref) == ()
    closure = reference_closure(store, (manifest_ref,))
    assert runtime.configuration_ref in closure

    store._path(runtime.configuration_ref).unlink()
    problems = verify_manifest(store, manifest_ref)
    assert problems and problems[0].code == "manifest_context"


async def test_bundle_export_and_verification_include_the_v2_runtime_object(
    tmp_path: Path,
) -> None:
    store = ObjectStore(tmp_path / "store")
    runtime = default_runtime(store)
    fixture = execution_fixture(store, subject_ids=("ok",), worker_repeats=1, runtime=runtime)
    result = await execute_plan(**fixture.arguments)
    assert isinstance(result, RunSucceeded), result
    manifest_ref = str(result.manifest_ref)
    assert verify_bundle(store, manifest_ref) == ()

    exported = export_bundle(store, manifest_ref, tmp_path / "export")
    assert exported._path(runtime.configuration_ref).exists()
    assert verify_bundle(exported, manifest_ref) == ()

    exported._path(runtime.configuration_ref).unlink()
    problems = verify_bundle(exported, manifest_ref)
    assert problems and problems[0].code == "bundle_integrity"


async def test_execution_rejects_a_missing_runtime_closure_before_any_worker_call(
    tmp_path: Path,
) -> None:
    store = ObjectStore(tmp_path)
    runtime = default_runtime(store)
    fixture = execution_fixture(store, subject_ids=("ok",), worker_repeats=1, runtime=runtime)
    store._path(runtime.configuration_ref).unlink()
    result = await execute_plan(**fixture.arguments)
    assert not isinstance(result, RunSucceeded)
    assert result.manifest is None and result.manifest_ref is None


def test_require_runtime_closure_is_a_noop_for_legacy_plans(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    fixture = execution_fixture(store, subject_ids=("ok",))
    plan = parse_execution_plan(json.loads(fixture.plan_bytes))
    require_runtime_closure(store, plan)  # must not raise; there is no runtime to check


async def test_report_pools_two_runs_bound_to_the_same_runtime_profile(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    runtime = default_runtime(store, id="pier", version="1.0.0")
    first_fixture = execution_fixture(
        store, subject_ids=("alpha",), worker_repeats=1, runtime=runtime
    )
    second_fixture = execution_fixture(
        store, subject_ids=("beta",), worker_repeats=1, runtime=runtime
    )
    first = await execute_plan(**first_fixture.arguments)
    second = await execute_plan(**second_fixture.arguments)
    assert isinstance(first, RunSucceeded) and isinstance(second, RunSucceeded)

    report = build_report(store, _report_config(first, second))
    assert report["comparisons"][0]["n"] == 2


async def test_report_rejects_pooling_across_different_runtime_profiles(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    first_fixture = execution_fixture(
        store,
        subject_ids=("alpha",),
        worker_repeats=1,
        runtime=default_runtime(store, id="pier", version="1.0.0"),
    )
    second_fixture = execution_fixture(
        store,
        subject_ids=("beta",),
        worker_repeats=1,
        runtime=default_runtime(store, id="pier", version="2.0.0"),
    )
    first = await execute_plan(**first_fixture.arguments)
    second = await execute_plan(**second_fixture.arguments)
    assert isinstance(first, RunSucceeded) and isinstance(second, RunSucceeded)

    with pytest.raises(ReportError, match="compatibility drift"):
        build_report(store, _report_config(first, second))


async def test_report_rejects_pooling_a_legacy_run_with_a_generic_runtime_run(
    tmp_path: Path,
) -> None:
    store = ObjectStore(tmp_path)
    legacy_fixture = execution_fixture(store, subject_ids=("alpha",), worker_repeats=1)
    generic_fixture = execution_fixture(
        store,
        subject_ids=("beta",),
        worker_repeats=1,
        runtime=default_runtime(store, id="pier", version="1.0.0"),
    )
    legacy = await execute_plan(**legacy_fixture.arguments)
    generic = await execute_plan(**generic_fixture.arguments)
    assert isinstance(legacy, RunSucceeded) and isinstance(generic, RunSucceeded)

    with pytest.raises(ReportError, match="compatibility drift"):
        build_report(store, _report_config(legacy, generic))


async def test_report_recomputation_reaches_the_runtime_closure_too(tmp_path: Path) -> None:
    """``build_report`` calls ``verify_manifest`` per manifest before it reads records."""
    store = ObjectStore(tmp_path)
    runtime = default_runtime(store)
    fixture = execution_fixture(store, subject_ids=("ok",), worker_repeats=1, runtime=runtime)
    result = await execute_plan(**fixture.arguments)
    assert isinstance(result, RunSucceeded), result

    store._path(runtime.configuration_ref).unlink()
    with pytest.raises(ReportError, match="invalid manifest"):
        build_report(store, _report_config(result))
