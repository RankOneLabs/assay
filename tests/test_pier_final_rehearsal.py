"""The final rehearsal ``docs/pier-integration.md`` describes, automated.

Verifies the fixed legacy bundle (the same fixture ``test_optional_jig.py``
proves verifies in a wheel install with no Jig at all) and a freshly
generated Pier bundle in one run, then scans the fresh bundle for a sentinel
that must never be reachable from it.

"No Jig" here means what it means for Pier specifically: neither
``assay.adapters.pier`` nor ``assay.investigations.pier_experiment`` import
Jig at all (unlike the legacy consistency/DRY investigations, which import it
lazily behind the ``legacy`` extra) -- this rehearsal proves that by running
the whole Pier path with no Jig import ever occurring, not by re-installing a
separate wheel outside the checkout the way ``test_optional_jig.py`` does for
the older legacy-bundle split. A real credential is never read or required:
the fake bridge below is what stands in for a real dispatch, and the paid
env gates are satisfied with an inert placeholder string, never a live key.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from assay.adapters.pier import BridgeEffectiveEnforcement, BridgeTrialResult
from assay.canonical import digest_bytes
from assay.investigations.correctness import DockerPythonRunner
from assay.investigations.pier_experiment import (
    EXPECTED_BRIDGE_LOCK_DIGEST,
    EXPECTED_DOCKER_VERSION,
    EXPECTED_MINI_SWE_AGENT_REVISION,
    EXPECTED_PIER_REVISION,
    PIER_BRIDGE_IMAGE_DIGEST,
    PIER_PAID_APPROVAL_ENV,
    PIER_PAID_CREDENTIAL_ENV,
    PierExperimentPrepared,
    PierExperimentSucceeded,
    prepare_pier_smoke,
    run_pier_smoke,
)
from assay.pier_protocol import ArtifactEntry, ArtifactManifest, PierExchange
from assay.store import ObjectStore
from assay.verify import verify_bundle, verify_manifest

ROOT = Path(__file__).resolve().parents[1]
LEGACY_FIXTURE_BUNDLE = ROOT / "tests" / "fixtures" / "legacy-0.1.0-bundle" / "bundle"
LEGACY_FIXTURE_MANIFEST_REF = (
    "sha256:7f60b6946084c4ef35c81fea380daa2c669a1f634e8edc85b11cf79cf97a3803"
)

# Never referenced by any artifact entry, manifest, or report -- a real
# reviewer or exported bundle must never be able to reach it. Standing in
# for the "hidden test/evaluator/object-metadata" sentinels
# tests/test_pier_secrecy.py already proves never reach a package; this
# rehearsal proves the symmetric claim at the export/report boundary.
_FORBIDDEN_HIDDEN_SENTINEL = "SENTINEL_HIDDEN_NEVER_EXPORTED_9c71"


def _qualified_inventory_ref(store: ObjectStore) -> str:
    """A real, recorded qualification matching every EXPECTED_* constant."""
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


class _RehearsalHandle:
    def __init__(self, exchange: PierExchange, store: ObjectStore) -> None:
        self._exchange = exchange
        self._store = store

    def run(self) -> BridgeTrialResult:
        # A store-only object, published directly and never referenced by
        # any artifact entry this trial returns -- the exported bundle's
        # reference closure must never reach it.
        self._store.publish_json({"never_exported": _FORBIDDEN_HIDDEN_SENTINEL})

        contents = {
            "raw_trajectory.json": b'{"steps": ["thought", "action", "submit"]}',
            "candidate.py": b"def solve():\n    return 42\n",
            "result.json": b'{"exit_status": "Submitted"}',
            "configuration.json": b'{"model": "anthropic/claude-3-haiku"}',
            "manifest_marker.json": b'{"manifest": "committed"}',
        }
        kinds: dict[str, Any] = {
            "raw_trajectory.json": "raw_trajectory",
            "candidate.py": "candidate",
            "result.json": "result",
            "configuration.json": "configuration",
            "manifest_marker.json": "manifest",
        }
        entries = tuple(
            ArtifactEntry(
                path=path,
                kind=kind,
                size_bytes=len(contents[path]),
                checksum=digest_bytes(contents[path]),
                utf8=True,
            )
            for path, kind in kinds.items()
        )
        manifest = ArtifactManifest(
            exchange=self._exchange,
            entries=entries,
            aggregate_bytes=sum(entry.size_bytes for entry in entries),
        )
        artifacts = {**contents, "manifest.json": manifest.model_dump_json().encode()}
        return BridgeTrialResult(
            exchange=self._exchange,
            status="succeeded",
            submission_ref=digest_bytes(contents["candidate.py"]),
            usage={"cost_usd": 0.72, "prompt_tokens": 100, "completion_tokens": 50},
            error_type=None,
            error_message=None,
            artifacts=artifacts,
        )

    def teardown(self) -> BridgeEffectiveEnforcement:
        return BridgeEffectiveEnforcement(
            containers_remaining=0, child_processes_remaining=0, teardown_completed=True
        )


class _RehearsalBridge:
    """Stands in for a real dispatch -- no network, no credential, ever read."""

    def __init__(self, store: ObjectStore) -> None:
        self._store = store

    def create(self, *, exchange: PierExchange, package: Mapping[str, str]) -> _RehearsalHandle:
        return _RehearsalHandle(exchange, self._store)


async def test_final_rehearsal_verifies_the_legacy_bundle_and_a_fresh_pier_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Half one: the fixed legacy bundle, the same fixture
    # tests/test_optional_jig.py proves verifies in a wheel install with no
    # Jig at all -- re-verified here as part of one rehearsal covering both
    # halves of the operational surface.
    legacy_store = ObjectStore(LEGACY_FIXTURE_BUNDLE)
    assert verify_manifest(legacy_store, LEGACY_FIXTURE_MANIFEST_REF) == ()
    assert verify_bundle(legacy_store, LEGACY_FIXTURE_MANIFEST_REF) == ()

    # Half two: a freshly generated Pier bundle, through the real
    # prepare_pier_smoke/run_pier_smoke path -- both paid-approval env gates
    # satisfied with an inert placeholder, never a real credential, since
    # the fake bridge above is what stands in for dispatch.
    monkeypatch.setenv(PIER_PAID_APPROVAL_ENV, "1")
    monkeypatch.setenv(PIER_PAID_CREDENTIAL_ENV, "sk-rehearsal-placeholder-not-a-real-key")
    store = ObjectStore(tmp_path / ".assay")
    inventory_ref = _qualified_inventory_ref(store)
    prepared = prepare_pier_smoke(store, inventory_ref=inventory_ref, runner=DockerPythonRunner())
    assert isinstance(prepared, PierExperimentPrepared)
    plan_bytes = store.read_bytes(prepared.plan_ref)
    destination = tmp_path / "rehearsal-bundles"

    result = await run_pier_smoke(
        store,
        plan_ref=prepared.plan_ref,
        authorization=digest_bytes(plan_bytes),
        bridge=_RehearsalBridge(store),
        allow_paid=True,
        inventory_ref=inventory_ref,
        export_destination=destination,
    )
    assert isinstance(result, PierExperimentSucceeded), result

    for name, report_ref in (
        ("abstraction", result.abstraction_report_ref),
        ("correctness", result.correctness_report_ref),
    ):
        bundle_store = ObjectStore(destination / name)
        assert verify_bundle(bundle_store, report_ref) == ()

        exported_bytes = b"".join(
            path.read_bytes() for path in sorted(bundle_store.objects.iterdir()) if path.is_file()
        )
        assert _FORBIDDEN_HIDDEN_SENTINEL.encode() not in exported_bytes, (
            f"the {name} bundle reached an object never referenced by any exported "
            "artifact or manifest"
        )
