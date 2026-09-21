"""End-to-end 0.2.0 runtime closure enforcement and cross-profile report isolation.

``execute_plan`` now accepts ``ExecutionPlanV2`` generically (the Pier cohort of
this epic wires a real backend to it; see ``assay.adapters.pier`` and
``experiments/pier_qualification/tests/test_pier_run.py``), so
``test_execution_accepts_v2_plans`` below exercises
that path directly with the ordinary fixture worker. The remaining tests in this
module still re-root a real, fully verified v1 run onto an equivalent v2 plan --
that re-rooting exercises the closure, verification, and report-fingerprint
machinery independently of which worker executed the underlying cells.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_execution import default_runtime, execution_fixture

from assay.canonical import canonical_json, digest_bytes
from assay.execution import RunSucceeded, execute_plan
from assay.models import (
    ReportConfig,
    RunManifest,
    RuntimeProfile,
    StatisticalProfile,
    parse_execution_plan,
)
from assay.planning import compile_plan_v2, require_runtime_closure
from assay.references import reference_closure
from assay.report_engine import ReportError, build_report
from assay.store import ObjectStore
from assay.verify import export_bundle, verify_bundle, verify_manifest


async def _v2_manifest_from_v1(
    store: ObjectStore, *, subject_ids: tuple[str, ...], runtime: RuntimeProfile
) -> str:
    """Re-root a real, verified v1 run onto an equivalent v2 plan.

    No v2 backend exists to execute a plan directly (out of scope for this cohort:
    ``execute_plan`` only accepts ``assay-execution-plan/0.1.0``). A v1 run's records
    are otherwise version-agnostic, so this republishes them under a fresh run id and
    an authorized v2 plan with the same governed content, giving the closure/
    verification/report tests a genuine manifest to exercise.
    """
    fixture = execution_fixture(
        store, subject_ids=subject_ids, worker_repeats=1, evaluator_repeats=1
    )
    result = await execute_plan(**fixture.arguments)
    assert isinstance(result, RunSucceeded), result
    old_manifest = result.manifest
    old_run_id = old_manifest.run_id
    old_plan_ref = old_manifest.plan_ref

    v1_plan = json.loads(fixture.plan_bytes)
    v2_plan = compile_plan_v2(
        fixture.snapshot,
        snapshot_ref=v1_plan["snapshot_ref"],
        worker_repeats=1,
        runtime=runtime,
    )
    v2_plan_ref = str(store.publish_bytes(canonical_json(v2_plan.model_dump(mode="json"))))
    new_run_id = f"v2-{old_run_id}"

    # Downstream records reference upstream ones by digest (an evaluation record's
    # source_references includes its execution outcome's ref, an operating record's
    # includes its execution/evaluation ref and its own nested accounting-provenance
    # "detail" object); rerooting a record changes its digest, so each substitution
    # must accumulate before the records that point to it reroot.
    replacements: dict[str, str] = {old_run_id: new_run_id, old_plan_ref: v2_plan_ref}

    def _reroot(ref: str) -> str:
        text = store.read_bytes(ref).decode()
        for old, new in replacements.items():
            text = text.replace(old, new)
        new_ref = str(store.publish_bytes(text.encode()))
        replacements[ref] = new_ref
        return new_ref

    execution_records = {k: _reroot(v) for k, v in old_manifest.execution_records.items()}
    evaluation_records = {k: _reroot(v) for k, v in old_manifest.evaluation_records.items()}
    for ref in old_manifest.operating_records.values():
        for source in json.loads(store.read_bytes(ref))["source_references"]:
            if source not in replacements and old_run_id in store.read_bytes(source).decode():
                _reroot(source)
    operating_records = {k: _reroot(v) for k, v in old_manifest.operating_records.items()}

    manifest = RunManifest(
        run_id=new_run_id,
        plan_ref=v2_plan_ref,
        status=old_manifest.status,
        execution_records=execution_records,
        evaluation_records=evaluation_records,
        operating_records=operating_records,
        missing_coordinates=old_manifest.missing_coordinates,
    )
    manifest_ref = str(store.publish_bytes(canonical_json(manifest.model_dump(mode="json"))))
    assert verify_manifest(store, manifest_ref) == (), verify_manifest(store, manifest_ref)
    return manifest_ref


def _report_config(*manifest_refs_and_records: tuple[str, tuple[str, ...]]) -> ReportConfig:
    return ReportConfig(
        manifest_refs=tuple(ref for ref, _ in manifest_refs_and_records),
        record_refs=tuple(ref for _, refs in manifest_refs_and_records for ref in refs),
        reference_arm="reference",
        candidates=("candidate",),
        evaluator_id="quality",
        metric="scalar",
        scalar_direction="higher_is_better",
        evaluator_repeat_aggregation="mean",
        worker_repeat_aggregation="mean",
        statistical_profile=StatisticalProfile(seed=9, bootstrap_samples=1000),
        engine_version="0.1.0",
    )


def _records(store: ObjectStore, manifest_ref: str) -> tuple[str, tuple[str, ...]]:
    manifest = RunManifest.model_validate_json(store.read_bytes(manifest_ref))
    return manifest_ref, tuple(sorted(manifest.evaluation_records.values()))


async def test_execution_accepts_v2_plans(tmp_path: Path) -> None:
    """A 0.2.0 plan with a fully declared runtime closure executes like any v1 plan."""
    store = ObjectStore(tmp_path)
    fixture = execution_fixture(store, subject_ids=("ok",), worker_repeats=1)
    v1_plan = json.loads(fixture.plan_bytes)
    v2_plan = compile_plan_v2(
        fixture.snapshot,
        snapshot_ref=v1_plan["snapshot_ref"],
        worker_repeats=1,
        runtime=default_runtime(store),
    )
    v2_plan_bytes = canonical_json(v2_plan.model_dump(mode="json"))
    arguments = {
        **fixture.arguments,
        "plan_bytes": v2_plan_bytes,
        "authorization": digest_bytes(v2_plan_bytes),
    }
    result = await execute_plan(**arguments)
    assert isinstance(result, RunSucceeded), result
    assert result.manifest.status == "complete"


async def test_execution_rejects_a_v2_plan_with_a_dangling_runtime_configuration(
    tmp_path: Path,
) -> None:
    """A v2 plan's runtime configuration must itself be stored, not merely referenced."""
    store = ObjectStore(tmp_path)
    fixture = execution_fixture(store, subject_ids=("ok",), worker_repeats=1)
    v1_plan = json.loads(fixture.plan_bytes)
    runtime = RuntimeProfile(
        id="pier", version="lock-v1", configuration_ref="sha256:" + "9" * 64
    )
    v2_plan = compile_plan_v2(
        fixture.snapshot,
        snapshot_ref=v1_plan["snapshot_ref"],
        worker_repeats=1,
        runtime=runtime,
    )
    v2_plan_bytes = canonical_json(v2_plan.model_dump(mode="json"))
    arguments = {
        **fixture.arguments,
        "plan_bytes": v2_plan_bytes,
        "authorization": digest_bytes(v2_plan_bytes),
    }
    result = await execute_plan(**arguments)
    assert not isinstance(result, RunSucceeded)
    assert result.manifest is None and result.manifest_ref is None


async def test_manifest_rooted_closure_requires_the_v2_runtime_object(tmp_path: Path) -> None:
    """A manifest/outcome/evidence-rooted walk must reach ``runtime.configuration_ref``.

    Before the discriminator-aware fix, ``_PATHS["assay-run-manifest/0.1.0"]["plan_ref"]``
    was hardcoded to the 0.1.0 path set, so a v2 plan reached via a manifest (rather than
    parsed directly) silently dropped its runtime edge -- this regresses that gap.
    """
    store = ObjectStore(tmp_path)
    runtime = default_runtime(store)
    manifest_ref = await _v2_manifest_from_v1(store, subject_ids=("ok",), runtime=runtime)

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
    manifest_ref = await _v2_manifest_from_v1(store, subject_ids=("ok",), runtime=runtime)
    # The source store also holds the real v1 run this was re-rooted from, so
    # verify_bundle's exact-closure check runs against the exported copy instead.
    exported = export_bundle(store, manifest_ref, tmp_path / "export")
    assert exported._path(runtime.configuration_ref).exists()
    assert verify_bundle(exported, manifest_ref) == ()

    exported._path(runtime.configuration_ref).unlink()
    problems = verify_bundle(exported, manifest_ref)
    assert problems and problems[0].code == "bundle_integrity"


def test_require_runtime_closure_is_a_noop_for_legacy_plans(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    fixture = execution_fixture(store, subject_ids=("ok",))
    plan = parse_execution_plan(json.loads(fixture.plan_bytes))
    require_runtime_closure(store, plan)  # must not raise; there is no runtime to check


async def test_report_pools_two_runs_bound_to_the_same_runtime_profile(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    runtime = default_runtime(store, id="pier", version="1.0.0")
    first = await _v2_manifest_from_v1(store, subject_ids=("alpha",), runtime=runtime)
    second = await _v2_manifest_from_v1(store, subject_ids=("beta",), runtime=runtime)

    report = build_report(store, _report_config(_records(store, first), _records(store, second)))
    assert report["comparisons"][0]["n"] == 2


async def test_report_rejects_pooling_across_different_runtime_profiles(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    first = await _v2_manifest_from_v1(
        store, subject_ids=("alpha",), runtime=default_runtime(store, id="pier", version="1.0.0")
    )
    second = await _v2_manifest_from_v1(
        store, subject_ids=("beta",), runtime=default_runtime(store, id="pier", version="2.0.0")
    )

    with pytest.raises(ReportError, match="compatibility drift"):
        build_report(store, _report_config(_records(store, first), _records(store, second)))


async def test_report_rejects_pooling_a_legacy_run_with_a_generic_runtime_run(
    tmp_path: Path,
) -> None:
    store = ObjectStore(tmp_path)
    legacy_fixture = execution_fixture(store, subject_ids=("alpha",), worker_repeats=1)
    legacy_result = await execute_plan(**legacy_fixture.arguments)
    assert isinstance(legacy_result, RunSucceeded), legacy_result
    legacy_ref = str(legacy_result.manifest_ref)

    generic_ref = await _v2_manifest_from_v1(
        store, subject_ids=("beta",), runtime=default_runtime(store, id="pier", version="1.0.0")
    )

    with pytest.raises(ReportError, match="compatibility drift"):
        build_report(
            store,
            _report_config(_records(store, legacy_ref), _records(store, generic_ref)),
        )


async def test_report_recomputation_reaches_the_runtime_closure_too(tmp_path: Path) -> None:
    """``build_report`` calls ``verify_manifest`` per manifest before it reads records."""
    store = ObjectStore(tmp_path)
    runtime = default_runtime(store)
    manifest_ref = await _v2_manifest_from_v1(store, subject_ids=("ok",), runtime=runtime)

    store._path(runtime.configuration_ref).unlink()
    with pytest.raises(ReportError, match="invalid manifest"):
        build_report(store, _report_config(_records(store, manifest_ref)))
