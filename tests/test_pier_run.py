from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest
from test_execution import execution_fixture

from assay._version import __version__
from assay.adapters.pier import BridgeEffectiveEnforcement, BridgeTrialResult, PierBridgeHandle
from assay.canonical import canonical_json, digest_bytes
from assay.investigations.pier_experiment import (
    EXPECTED_BRIDGE_LOCK_DIGEST,
    EXPECTED_DOCKER_VERSION,
    EXPECTED_MINI_SWE_AGENT_REVISION,
    EXPECTED_PIER_REVISION,
    PIER_BRIDGE_IMAGE_DIGEST,
    PIER_PAID_APPROVAL_ENV,
    PIER_PAID_CREDENTIAL_ENV,
    PierExperimentFailed,
    PierExperimentPrepared,
    PierExperimentSucceeded,
    prepare_pier_qualification,
    prepare_pier_smoke,
    run_pier_qualification,
    run_pier_smoke,
)
from assay.models import ReportConfig, RunManifest, StatisticalProfile
from assay.pier_protocol import ArtifactEntry, ArtifactManifest, PierExchange
from assay.references import reference_closure
from assay.report_engine import ReportError, build_report
from assay.store import ObjectStore


@pytest.fixture(autouse=True)
def _paid_gates_satisfied(monkeypatch: pytest.MonkeyPatch) -> None:
    """This module exercises real dispatch given every gate is satisfied --
    ``tests/test_pier_acceptance.py`` covers each gate's own rejection,
    including this env-level approval/credential pair, independently."""
    monkeypatch.setenv(PIER_PAID_APPROVAL_ENV, "1")
    monkeypatch.setenv(PIER_PAID_CREDENTIAL_ENV, "sk-not-a-real-key")


def _qualified_inventory_ref(store: ObjectStore) -> str:
    """A qualification matching every EXPECTED_* constant pier_experiment pins.

    ``run_pier_*`` requires a real, explicit ``inventory_ref`` -- it never
    falls back to the synthetic default the way ``prepare_pier_*`` does.
    """
    return str(
        store.publish_json(
            {
                "schema_version": "assay-pier-qualification/0.1.0",
                "bridge": {
                    "pier_revision": EXPECTED_PIER_REVISION,
                    "mini_swe_agent_revision": EXPECTED_MINI_SWE_AGENT_REVISION,
                    "lock_digest": EXPECTED_BRIDGE_LOCK_DIGEST,
                    "bridge_image_digest": PIER_BRIDGE_IMAGE_DIGEST,
                },
                "measured": {
                    "docker_version": EXPECTED_DOCKER_VERSION,
                    "network_none_verified": True,
                    "uid": 1000,
                    "gid": 1000,
                },
                "qualified_at": "2026-09-11T00:00:00Z",
                "outcome": "succeeded",
            }
        )
    )


def _manifest_and_artifacts(exchange: PierExchange) -> tuple[ArtifactManifest, dict[str, bytes]]:
    contents = {
        "raw_trajectory.json": b'{"steps": ["thought", "action", "submit"]}',
        "candidate.txt": b"def solve():\n    return 42\n",
        "result.json": b'{"passed": true, "exit_status": "Submitted"}',
        "configuration.json": b'{"model": "anthropic/claude-3-haiku"}',
        "manifest_marker.json": b'{"manifest": "committed"}',
    }
    kinds = {
        "raw_trajectory.json": "raw_trajectory",
        "candidate.txt": "candidate",
        "result.json": "result",
        "configuration.json": "configuration",
        "manifest_marker.json": "manifest",
    }
    entries = tuple(
        ArtifactEntry(
            path=path,
            kind=kind,  # type: ignore[arg-type]
            size_bytes=len(contents[path]),
            checksum=digest_bytes(contents[path]),
            utf8=True,
        )
        for path, kind in kinds.items()
    )
    manifest = ArtifactManifest(
        exchange=exchange, entries=entries, aggregate_bytes=sum(e.size_bytes for e in entries)
    )
    manifest_bytes = canonical_json(manifest.model_dump(mode="json"))
    artifacts = {**contents, "manifest.json": manifest_bytes}
    return manifest, artifacts


class _Handle:
    def __init__(self, result: BridgeTrialResult) -> None:
        self._result = result

    def run(self) -> BridgeTrialResult:
        return self._result

    def teardown(self) -> BridgeEffectiveEnforcement:
        return BridgeEffectiveEnforcement(
            containers_remaining=0, child_processes_remaining=0, teardown_completed=True
        )


class _AlwaysSucceedsBridge:
    def create(self, *, exchange: PierExchange, package: Mapping[str, str]) -> PierBridgeHandle:
        _, artifacts = _manifest_and_artifacts(exchange)
        return _Handle(
            BridgeTrialResult(
                exchange=exchange,
                status="succeeded",
                submission_ref=digest_bytes(artifacts["candidate.txt"]),
                error_type=None,
                error_message=None,
                usage={"cost_usd": 0.72, "prompt_tokens": 100, "completion_tokens": 50},
                artifacts=artifacts,
            )
        )


async def test_full_successful_smoke_run_publishes_evidence_reachable_from_closure(
    tmp_path: Path,
) -> None:
    store = ObjectStore(tmp_path / ".assay")
    inventory_ref = _qualified_inventory_ref(store)
    prepared = prepare_pier_smoke(store, inventory_ref=inventory_ref)
    assert isinstance(prepared, PierExperimentPrepared)
    plan_bytes = store.read_bytes(prepared.plan_ref)
    result = await run_pier_smoke(
        store,
        plan_ref=prepared.plan_ref,
        authorization=digest_bytes(plan_bytes),
        bridge=_AlwaysSucceedsBridge(),
        allow_paid=True,
        inventory_ref=inventory_ref,
    )
    assert isinstance(result, PierExperimentSucceeded), result

    manifest = RunManifest.model_validate_json(store.read_bytes(result.manifest_ref))
    assert manifest.status == "complete"
    assert len(manifest.execution_records) == 4

    closure = reference_closure(store, (result.manifest_ref,))
    assert result.manifest_ref in closure
    for ref in manifest.execution_records.values():
        assert ref in closure
    for ref in manifest.operating_records.values():
        assert ref in closure

    for ref in manifest.execution_records.values():
        outcome = json.loads(store.read_bytes(ref))
        assert outcome["status"] == "succeeded"
        output = json.loads(store.read_bytes(outcome["output_ref"]))
        for key in (
            "candidate_ref",
            "raw_trajectory_ref",
            "result_ref",
            "configuration_ref",
            "manifest_ref",
        ):
            assert output[key] is not None
            assert output[key] in closure, f"{key} not reachable from the outcome closure"
        # No "transcript" kind entry is present in this fixture's manifest --
        # ATIF absence must never fail a run, and must be an explicit,
        # distinguishable tri-state, not merely a silently-null field.
        assert output["transcript_ref"] is None
        assert output["transcript_status"] == "unavailable"


async def test_successful_run_produces_separate_paired_reports_and_export_bundles(
    tmp_path: Path,
) -> None:
    """Acceptance criterion: a successful run produces separate abstraction
    and correctness reports and exact verified bundle exports."""
    from assay.verify import verify_bundle as _verify_bundle

    store = ObjectStore(tmp_path / ".assay")
    inventory_ref = _qualified_inventory_ref(store)
    prepared = prepare_pier_smoke(store, inventory_ref=inventory_ref)
    assert isinstance(prepared, PierExperimentPrepared)
    plan_bytes = store.read_bytes(prepared.plan_ref)
    destination = tmp_path / "export"
    result = await run_pier_smoke(
        store,
        plan_ref=prepared.plan_ref,
        authorization=digest_bytes(plan_bytes),
        bridge=_AlwaysSucceedsBridge(),
        allow_paid=True,
        inventory_ref=inventory_ref,
        export_destination=destination,
    )
    assert isinstance(result, PierExperimentSucceeded), result
    assert result.abstraction_report_ref != result.correctness_report_ref

    abstraction_report = json.loads(store.read_bytes(result.abstraction_report_ref))
    correctness_report = json.loads(store.read_bytes(result.correctness_report_ref))
    assert abstraction_report != correctness_report

    abstraction_store = ObjectStore(destination / "abstraction")
    correctness_store = ObjectStore(destination / "correctness")
    assert _verify_bundle(abstraction_store, result.abstraction_report_ref) == ()
    assert _verify_bundle(correctness_store, result.correctness_report_ref) == ()

    # Re-running into the same destination must not silently overwrite it.
    replay = await run_pier_smoke(
        store,
        plan_ref=prepared.plan_ref,
        authorization=digest_bytes(plan_bytes),
        bridge=_AlwaysSucceedsBridge(),
        allow_paid=True,
        inventory_ref=inventory_ref,
        export_destination=destination,
    )
    assert isinstance(replay, PierExperimentFailed)
    assert "already exists" in replay.message


async def test_execution_requires_paid_approval(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / ".assay")
    prepared = prepare_pier_smoke(store)
    assert isinstance(prepared, PierExperimentPrepared)
    plan_bytes = store.read_bytes(prepared.plan_ref)
    result = await run_pier_smoke(
        store,
        plan_ref=prepared.plan_ref,
        authorization=digest_bytes(plan_bytes),
        bridge=_AlwaysSucceedsBridge(),
        allow_paid=False,
    )
    assert isinstance(result, PierExperimentFailed)
    assert "allow_paid" in result.message


async def test_paid_execution_requires_an_explicit_inventory_ref(tmp_path: Path) -> None:
    """Unlike ``prepare_pier_*``, a paid run never falls back to the
    synthetic default qualification -- an omitted ``inventory_ref`` fails
    the run rather than silently authorizing dispatch against unmeasured
    evidence."""
    store = ObjectStore(tmp_path / ".assay")
    inventory_ref = _qualified_inventory_ref(store)
    prepared = prepare_pier_smoke(store, inventory_ref=inventory_ref)
    assert isinstance(prepared, PierExperimentPrepared)
    plan_bytes = store.read_bytes(prepared.plan_ref)
    result = await run_pier_smoke(
        store,
        plan_ref=prepared.plan_ref,
        authorization=digest_bytes(plan_bytes),
        bridge=_AlwaysSucceedsBridge(),
        allow_paid=True,
    )
    assert isinstance(result, PierExperimentFailed)
    assert "inventory_ref" in result.message


async def test_different_pier_profile_manifests_cannot_be_pooled_in_one_report(
    tmp_path: Path,
) -> None:
    store = ObjectStore(tmp_path / ".assay")
    inventory_ref = _qualified_inventory_ref(store)
    smoke_prepared = prepare_pier_smoke(store, inventory_ref=inventory_ref)
    qualification_prepared = prepare_pier_qualification(store, inventory_ref=inventory_ref)
    assert isinstance(smoke_prepared, PierExperimentPrepared)
    assert isinstance(qualification_prepared, PierExperimentPrepared)

    smoke_bytes = store.read_bytes(smoke_prepared.plan_ref)
    qualification_bytes = store.read_bytes(qualification_prepared.plan_ref)

    smoke_result = await run_pier_smoke(
        store,
        plan_ref=smoke_prepared.plan_ref,
        authorization=digest_bytes(smoke_bytes),
        bridge=_AlwaysSucceedsBridge(),
        allow_paid=True,
        inventory_ref=inventory_ref,
    )
    qualification_result = await run_pier_qualification(
        store,
        plan_ref=qualification_prepared.plan_ref,
        authorization=digest_bytes(qualification_bytes),
        bridge=_AlwaysSucceedsBridge(),
        allow_paid=True,
        inventory_ref=inventory_ref,
    )
    assert isinstance(smoke_result, PierExperimentSucceeded)
    assert isinstance(qualification_result, PierExperimentSucceeded)

    config = ReportConfig(
        manifest_refs=(smoke_result.manifest_ref, qualification_result.manifest_ref),
        record_refs=(),
        reference_arm="inconsistent",
        candidates=("clean",),
        evaluator_id="abstraction",
        metric="ordinal",
        categories=("duplicated", "mixed", "reused"),
        evaluator_repeat_aggregation="median",
        worker_repeat_aggregation="median",
        statistical_profile=StatisticalProfile(seed=1, bootstrap_samples=100),
        engine_version=__version__,
    )
    with pytest.raises(ReportError, match="compatibility drift"):
        build_report(store, config)


async def test_legacy_v1_and_pier_v2_manifests_cannot_be_pooled_in_one_report(
    tmp_path: Path,
) -> None:
    """A legacy (jig-based, assay-execution-plan/0.1.0) manifest and a Pier
    (assay-execution-plan/0.2.0) manifest must never pool into one report --
    the 0.1.0 fingerprint binds jig_revision, the 0.2.0 fingerprint binds
    runtime identity instead, so the two are never coincidentally equal."""
    from assay.execution import RunSucceeded
    from assay.execution import execute_plan as _execute_plan

    store = ObjectStore(tmp_path / ".assay")
    legacy_fixture = execution_fixture(store, subject_ids=("ok",))
    legacy_result = await _execute_plan(**legacy_fixture.arguments)
    assert isinstance(legacy_result, RunSucceeded), legacy_result

    inventory_ref = _qualified_inventory_ref(store)
    smoke_prepared = prepare_pier_smoke(store, inventory_ref=inventory_ref)
    assert isinstance(smoke_prepared, PierExperimentPrepared)
    smoke_bytes = store.read_bytes(smoke_prepared.plan_ref)
    smoke_result = await run_pier_smoke(
        store,
        plan_ref=smoke_prepared.plan_ref,
        authorization=digest_bytes(smoke_bytes),
        bridge=_AlwaysSucceedsBridge(),
        allow_paid=True,
        inventory_ref=inventory_ref,
    )
    assert isinstance(smoke_result, PierExperimentSucceeded), smoke_result

    config = ReportConfig(
        manifest_refs=(str(legacy_result.manifest_ref), smoke_result.manifest_ref),
        record_refs=(),
        reference_arm="reference",
        candidates=("candidate",),
        evaluator_id="quality",
        metric="scalar",
        scalar_direction="higher_is_better",
        evaluator_repeat_aggregation="mean",
        worker_repeat_aggregation="mean",
        statistical_profile=StatisticalProfile(seed=1, bootstrap_samples=100),
        engine_version=__version__,
    )
    # Whichever manifest ref sorts first, build_report rejects the pool: the
    # legacy snapshot has no "abstraction"/"correctness" evaluator and Pier's
    # snapshot has no "quality" evaluator, so the per-manifest evaluator
    # check alone already forbids pooling them -- on top of, independently
    # of, the 0.1.0-vs-0.2.0 fingerprint the two plans would also fail on
    # (jig_revision vs runtime) if a shared evaluator id ever let the check
    # get that far.
    with pytest.raises(ReportError, match="evaluator or arm absent|compatibility drift"):
        build_report(store, config)
