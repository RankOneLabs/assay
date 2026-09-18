"""Declaring evidence and publishing it are separate steps.

``_publish_available_artifacts`` enforces the artifact byte ceilings before
anything reaches the store, so a bridge response can verify perfectly against
the bytes that crossed the boundary while the bytes backing a required kind
never got published. ``verify_artifact_bytes`` cannot see that: it is handed
the raw mapping, where those bytes are present either way. Only ``_settle``'s
own check observes the difference, and before it existed the gap surfaced as
a ``WorkerSuccess`` whose ``result_ref``/``candidate_ref``/... were null --
indistinguishable downstream from a trial that genuinely produced nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from assay.adapters.pier import (
    BridgeEffectiveEnforcement,
    BridgeTrialResult,
    PierAdapter,
    PierBridgeHandle,
)
from assay.canonical import canonical_json, digest_bytes
from assay.execution import WorkerFailure, WorkerSuccess
from assay.models import CellCoordinate
from assay.pier_protocol import (
    MANIFEST_PATH,
    MAX_AGGREGATE_ARTIFACT_BYTES,
    MAX_ARTIFACT_BYTES,
    REQUIRED_SUCCESS_KINDS,
    ArtifactEntry,
    ArtifactManifest,
    PierExchange,
    RuntimeBinding,
)
from assay.store import ObjectStore

REQUIRED_REF_FIELDS = {
    "raw_trajectory": "raw_trajectory_ref",
    "candidate": "candidate_ref",
    "result": "result_ref",
    "configuration": "configuration_ref",
}

_CONTENTS: dict[str, bytes] = {
    "raw_trajectory.json": b'{"steps": ["thought", "submit"]}',
    "candidate.txt": b"def solve():\n    return 42\n",
    "result.json": b'{"passed": true, "exit_status": "Submitted"}',
    "configuration.json": b'{"model": "anthropic/claude-3-haiku"}',
}
_KINDS: dict[str, str] = {
    "raw_trajectory.json": "raw_trajectory",
    "candidate.txt": "candidate",
    "result.json": "result",
    "configuration.json": "configuration",
}


def _binding() -> RuntimeBinding:
    return RuntimeBinding(
        runtime_version="lock-v1",
        image_digest="sha256:" + "1" * 64,
        configuration_ref="sha256:" + "2" * 64,
        package_digest="sha256:" + "0" * 64,
    )


def _coordinate() -> CellCoordinate:
    return CellCoordinate(
        subject_id="s1", arm_id="a1", worker_repeat=0, realization_ref="sha256:" + "0" * 64
    )


def _manifest_and_artifacts(
    exchange: PierExchange, *, extras: dict[str, bytes] | None = None
) -> tuple[ArtifactManifest, dict[str, bytes]]:
    entries = tuple(
        ArtifactEntry(
            path=path,
            kind=kind,  # type: ignore[arg-type]
            size_bytes=len(_CONTENTS[path]),
            checksum=digest_bytes(_CONTENTS[path]),
            utf8=True,
        )
        for path, kind in _KINDS.items()
    )
    manifest = ArtifactManifest(
        exchange=exchange, entries=entries, aggregate_bytes=sum(e.size_bytes for e in entries)
    )
    artifacts = {
        **(extras or {}),
        **_CONTENTS,
        MANIFEST_PATH: canonical_json(manifest.model_dump(mode="json")),
    }
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


class _Bridge:
    """Returns a well-formed success, plus whatever extra artifacts a test names."""

    def __init__(self, extras: dict[str, bytes] | None = None) -> None:
        self.extras = extras

    def create(self, *, exchange: PierExchange, package: dict[str, str]) -> PierBridgeHandle:
        _, artifacts = _manifest_and_artifacts(exchange, extras=self.extras)
        return _Handle(
            BridgeTrialResult(
                exchange=exchange,
                status="succeeded",
                submission_ref=digest_bytes(artifacts["candidate.txt"]),
                error_type=None,
                error_message=None,
                usage={"cost_usd": 0.01},
                artifacts=artifacts,
            )
        )


def _adapter(tmp_path: Path, bridge: Any) -> PierAdapter:
    return PierAdapter(
        store=ObjectStore(tmp_path / ".assay"),
        bridge=bridge,
        binding=_binding(),
        model_route={"model": "anthropic/claude-3-haiku", "provider": "amazon-bedrock"},
        trial_limits={"cpu": 1, "memory_mb": 512, "timeout_s": 60},
    )


async def _run(adapter: PierAdapter) -> Any:
    return await adapter.run_cell(
        input_value={"task": "do it", "repository": {"a.py": "x = 1\n"}}, coordinate=_coordinate()
    )


async def test_ordinary_success_publishes_every_required_ref(tmp_path: Path) -> None:
    result = await _run(_adapter(tmp_path, _Bridge()))
    assert isinstance(result, WorkerSuccess)
    for field in REQUIRED_REF_FIELDS.values():
        assert result.output[field] is not None, field
    assert result.output["manifest_ref"] is not None


async def test_an_undeclared_extra_cannot_crowd_out_declared_evidence(tmp_path: Path) -> None:
    """The budget is spent on the manifest and what it declares first.

    ``aggregate-hog.bin`` sorts before every declared path and, published in
    mapping order, would consume the entire aggregate ceiling and leave the
    real evidence unpublished. A bridge does not get to choose which
    evidence survives by naming a large extra early.
    """
    hog = {"aggregate-hog.bin": b"\x00" * MAX_ARTIFACT_BYTES}
    result = await _run(_adapter(tmp_path, _Bridge(extras=hog)))
    assert isinstance(result, WorkerSuccess)
    for field in REQUIRED_REF_FIELDS.values():
        assert result.output[field] is not None, field
    refs = result.trace["artifact_refs"]
    assert set(_CONTENTS) <= set(refs)


async def test_unpublished_required_evidence_fails_instead_of_emitting_a_null_ref(
    tmp_path: Path,
) -> None:
    """Enough undeclared extras to exhaust the aggregate ceiling before the
    declared evidence would be reached under the old mapping-order publish.

    The manifest still verifies -- the bytes are all present in the mapping
    that crossed the boundary -- so nothing before this check can see the
    problem. The cell must fail, not succeed with holes in its output.
    """
    # Named to sort ahead of every declared path: in mapping order these are
    # reached first and spend the whole aggregate ceiling.
    extras: dict[str, bytes] = {
        f"aaa-{index:02d}.bin": b"\x00" * MAX_ARTIFACT_BYTES
        for index in range(MAX_AGGREGATE_ARTIFACT_BYTES // MAX_ARTIFACT_BYTES)
    }
    adapter = _adapter(tmp_path, _Bridge(extras=extras))

    # Publish in the bridge's own mapping order, as the adapter used to: the
    # extras sort first, so every declared artifact is skipped for budget.
    import assay.adapters.pier as pier_module

    original = pier_module._publish_available_artifacts

    def unordered(store: Any, artifacts: Any, *, priority: Any = frozenset()) -> dict[str, str]:
        return original(store, artifacts, priority=frozenset())

    pier_module._publish_available_artifacts = unordered  # type: ignore[assignment]
    try:
        result = await _run(adapter)
    finally:
        pier_module._publish_available_artifacts = original  # type: ignore[assignment]

    assert isinstance(result, WorkerFailure)
    assert result.error_type == "UnpublishedEvidence"
    assert result.trace is not None
    assert result.trace["rejection_reason"] == "unpublished_evidence"
    for kind in REQUIRED_SUCCESS_KINDS:
        assert kind in result.message


async def test_unpublished_manifest_is_reported_as_missing_evidence(tmp_path: Path) -> None:
    """``manifest.json`` is the binding document and never one of the
    manifest's own entries, so its ref is resolved by reserved path -- and a
    success must not report a null one."""
    adapter = _adapter(tmp_path, _Bridge())
    import assay.adapters.pier as pier_module

    original = pier_module._publish_available_artifacts

    def without_manifest(
        store: Any, artifacts: Any, *, priority: Any = frozenset()
    ) -> dict[str, str]:
        refs = original(store, artifacts, priority=priority)
        refs.pop(MANIFEST_PATH, None)
        return refs

    pier_module._publish_available_artifacts = without_manifest  # type: ignore[assignment]
    try:
        result = await _run(adapter)
    finally:
        pier_module._publish_available_artifacts = original  # type: ignore[assignment]

    assert isinstance(result, WorkerFailure)
    assert result.error_type == "UnpublishedEvidence"
    assert "manifest" in result.message


def test_a_maximal_honest_manifest_still_publishes_in_full(tmp_path: Path) -> None:
    """The manifest is bounded per-artifact but excluded from the aggregate.

    A manifest may declare up to ``MAX_AGGREGATE_ARTIFACT_BYTES`` of
    artifacts. Charging the manifest itself to that same budget would evict a
    declared entry to make room for the document declaring it, so an honest
    bridge at the ceiling would fail the new required-ref check.
    """
    from assay.adapters.pier import _publish_available_artifacts

    store = ObjectStore(tmp_path / ".assay")
    declared = {
        f"declared-{index}.bin": b"\x00" * MAX_ARTIFACT_BYTES
        for index in range(MAX_AGGREGATE_ARTIFACT_BYTES // MAX_ARTIFACT_BYTES)
    }
    artifacts = {**declared, MANIFEST_PATH: b'{"schema_version": "x"}'}
    refs = _publish_available_artifacts(
        store, artifacts, priority=frozenset({MANIFEST_PATH, *declared})
    )
    assert set(refs) == set(artifacts)


@pytest.mark.parametrize("kind", sorted(REQUIRED_SUCCESS_KINDS))
def test_every_required_kind_has_an_output_ref_field(kind: str) -> None:
    """The failure this module guards is only meaningful while each required
    kind actually surfaces as a ref a downstream consumer reads."""
    assert kind in REQUIRED_REF_FIELDS
