from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from assay.canonical import digest_bytes
from assay.models import CellCoordinate
from assay.pier_protocol import (
    MAX_AGGREGATE_ARTIFACT_BYTES,
    MAX_ARTIFACT_BYTES,
    ArtifactEntry,
    ArtifactManifest,
    ManifestRejected,
    RuntimeBinding,
    bind_exchange,
    verify_artifact_bytes,
)
from assay.references import reference_closure
from assay.store import ObjectStore


def _coordinate() -> CellCoordinate:
    return CellCoordinate(
        subject_id="s1", arm_id="a1", worker_repeat=0, realization_ref="sha256:" + "0" * 64
    )


def _binding() -> dict[str, str]:
    return {
        "runtime_version": "lock-v1",
        "image_digest": "sha256:" + "1" * 64,
        "configuration_ref": "sha256:" + "2" * 64,
        "package_digest": "sha256:" + "3" * 64,
    }


def _entry(path: str, data: bytes, kind: str = "candidate", utf8: bool = True) -> ArtifactEntry:
    return ArtifactEntry(
        path=path, kind=kind, size_bytes=len(data), checksum=digest_bytes(data), utf8=utf8
    )  # type: ignore[arg-type]


def test_oversized_artifact_is_rejected_by_the_type() -> None:
    with pytest.raises(ValidationError):
        ArtifactEntry(
            path="candidate.txt",
            kind="candidate",
            size_bytes=MAX_ARTIFACT_BYTES + 1,
            checksum="sha256:" + "0" * 64,
            utf8=True,
        )  # type: ignore[arg-type]


def test_malformed_checksum_is_rejected_by_the_type() -> None:
    with pytest.raises(ValidationError):
        ArtifactEntry(
            path="candidate.txt", kind="candidate", size_bytes=1, checksum="not-a-digest", utf8=True
        )  # type: ignore[arg-type]


def test_unknown_kind_is_rejected_by_the_type() -> None:
    with pytest.raises(ValidationError):
        ArtifactEntry(
            path="candidate.txt",
            kind="not-a-real-kind",
            size_bytes=1,
            checksum="sha256:" + "0" * 64,
            utf8=True,
        )  # type: ignore[arg-type]


def test_aggregate_limit_is_enforced() -> None:
    exchange = bind_exchange(coordinate=_coordinate(), binding=RuntimeBinding(**_binding()))
    huge = MAX_AGGREGATE_ARTIFACT_BYTES + 1
    entry = ArtifactEntry(
        path="candidate.bin",
        kind="candidate",
        size_bytes=MAX_ARTIFACT_BYTES,
        checksum="sha256:" + "0" * 64,
        utf8=False,
    )  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="aggregate_bytes"):
        ArtifactManifest(exchange=exchange, entries=(entry,), aggregate_bytes=huge)


def test_terminal_error_artifact_is_a_typed_worker_failure_boundary() -> None:
    """A checksum-invalid artifact raises the typed ``ManifestRejected`` a worker
    converts to a terminal ``WorkerFailure`` -- never a bare/uncaught exception."""

    exchange = bind_exchange(coordinate=_coordinate(), binding=RuntimeBinding(**_binding()))
    data = b"trajectory bytes"
    entry = _entry("raw_trajectory.json", data, kind="raw_trajectory")
    manifest = ArtifactManifest(exchange=exchange, entries=(entry,), aggregate_bytes=len(data))
    with pytest.raises(ManifestRejected):
        verify_artifact_bytes(manifest, artifact_bytes={"raw_trajectory.json": b"forged bytes!!"})


def test_independent_partial_artifacts_remain_reachable_via_object_refs(tmp_path: Path) -> None:
    """Even when a run fails overall, valid partial evidence published under
    ``assay_object_refs`` stays reachable from the closure walk -- the same
    generic escape hatch every other governed document already uses."""
    store = ObjectStore(tmp_path / ".assay")
    raw_trajectory_ref = str(store.publish_json({"steps": ["thought", "action"]}))
    candidate_ref = str(store.publish_json({"text": "partial candidate"}))
    atif_unavailable_ref = str(
        store.publish_json({"kind": "atif", "available": False, "reason": "derivation failed"})
    )
    trace = {
        "outcome": "failed",
        "atif": {"available": False},
        "assay_object_refs": [raw_trajectory_ref, candidate_ref, atif_unavailable_ref],
    }
    trace_ref = str(store.publish_json(trace))
    closure = reference_closure(store, (trace_ref,))
    assert {trace_ref, raw_trajectory_ref, candidate_ref, atif_unavailable_ref} <= closure


def test_atif_unavailable_is_recorded_not_treated_as_missing_evidence() -> None:
    """ATIF is an optional derived view; a manifest with every required kind but
    no transcript still reports complete required-success evidence."""

    exchange = bind_exchange(coordinate=_coordinate(), binding=RuntimeBinding(**_binding()))
    kinds = ["raw_trajectory", "candidate", "result", "configuration", "manifest"]
    entries = tuple(
        _entry(f"{kind}.json", f'{{"kind": "{kind}"}}'.encode(), kind=kind) for kind in kinds
    )
    manifest = ArtifactManifest(
        exchange=exchange, entries=entries, aggregate_bytes=sum(e.size_bytes for e in entries)
    )
    assert manifest.has_required_success_evidence()
    assert "transcript" not in manifest.kinds()
