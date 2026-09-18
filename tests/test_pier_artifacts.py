from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from assay.canonical import digest_bytes
from assay.models import CellCoordinate
from assay.pier_protocol import (
    MANIFEST_PATH,
    MAX_AGGREGATE_ARTIFACT_BYTES,
    MAX_ARTIFACT_BYTES,
    REQUIRED_SUCCESS_KINDS,
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


def test_the_manifest_is_not_one_of_the_artifacts_it_binds() -> None:
    """``manifest`` was a required success kind that nothing could honestly
    satisfy: the entry would have had to declare the checksum of the bytes
    carrying that checksum. Every fixture author who met the requirement met
    it with a decoy file, so the "manifest evidence" a success was gated on
    was reliably not the manifest."""
    assert "manifest" not in REQUIRED_SUCCESS_KINDS
    assert {"raw_trajectory", "candidate", "result", "configuration"} == REQUIRED_SUCCESS_KINDS


def test_an_entry_cannot_claim_the_manifests_own_path() -> None:
    """Reserving the path turns the fixed point into a typed rejection at the
    boundary rather than something each writer rediscovers by trial and
    error -- and stops an entry from describing a decoy that merely sits
    where the manifest belongs."""
    with pytest.raises(ValidationError, match="cannot declare itself"):
        _entry(MANIFEST_PATH, b"{}", kind="result")


def test_manifest_kind_is_no_longer_a_declarable_kind() -> None:
    with pytest.raises(ValidationError):
        _entry("manifest-evidence.json", b"{}", kind="manifest")


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


def test_configuration_entry_claiming_non_utf8_is_rejected_by_the_type() -> None:
    """A structured JSON kind cannot declare utf8=False -- nothing about
    ``configuration`` is ever legitimately binary."""
    with pytest.raises(ValidationError, match="utf8=True"):
        _entry("configuration.json", b'{"model": "x"}', kind="configuration", utf8=False)


@pytest.mark.parametrize("kind", ["raw_trajectory", "result", "configuration"])
def test_structured_kinds_reject_non_utf8_declaration(kind: str) -> None:
    with pytest.raises(ValidationError, match="utf8=True"):
        _entry(f"{kind}.json", b"{}", kind=kind, utf8=False)


def test_candidate_entry_may_declare_non_utf8() -> None:
    """Arbitrary candidate source is never required to be UTF-8 or JSON."""
    _entry("candidate.bin", b"\xff\xfe", kind="candidate", utf8=False)


def test_configuration_entry_with_utf8_valid_non_json_bytes_is_rejected() -> None:
    """The UTF-8 rule and the "type" (JSON-parses) rule are independent
    checks: text that is valid UTF-8 but not valid JSON must still fail for
    a structured kind."""
    exchange = bind_exchange(coordinate=_coordinate(), binding=RuntimeBinding(**_binding()))
    data = b"this is not json"
    entry = _entry("configuration.json", data, kind="configuration", utf8=True)
    manifest = ArtifactManifest(exchange=exchange, entries=(entry,), aggregate_bytes=len(data))
    with pytest.raises(ManifestRejected, match="valid JSON"):
        verify_artifact_bytes(manifest, artifact_bytes={"configuration.json": data})


def test_configuration_entry_with_valid_json_is_accepted() -> None:
    exchange = bind_exchange(coordinate=_coordinate(), binding=RuntimeBinding(**_binding()))
    data = b'{"model": "anthropic/claude-3-haiku"}'
    entry = _entry("configuration.json", data, kind="configuration", utf8=True)
    manifest = ArtifactManifest(exchange=exchange, entries=(entry,), aggregate_bytes=len(data))
    verify_artifact_bytes(manifest, artifact_bytes={"configuration.json": data})


def test_candidate_entry_declared_utf8_is_not_required_to_be_json() -> None:
    """Only the four structured kinds get the JSON "type" rule; candidate
    text declared UTF-8 is still never required to parse as JSON."""
    exchange = bind_exchange(coordinate=_coordinate(), binding=RuntimeBinding(**_binding()))
    data = b"def solve():\n    return 42\n"
    entry = _entry("candidate.txt", data, kind="candidate", utf8=True)
    manifest = ArtifactManifest(exchange=exchange, entries=(entry,), aggregate_bytes=len(data))
    verify_artifact_bytes(manifest, artifact_bytes={"candidate.txt": data})


def test_atif_unavailable_is_recorded_not_treated_as_missing_evidence() -> None:
    """ATIF is an optional derived view; a manifest with every required kind but
    no transcript still reports complete required-success evidence."""

    exchange = bind_exchange(coordinate=_coordinate(), binding=RuntimeBinding(**_binding()))
    kinds = ["raw_trajectory", "candidate", "result", "configuration"]
    entries = tuple(
        _entry(f"{kind}.json", f'{{"kind": "{kind}"}}'.encode(), kind=kind) for kind in kinds
    )
    manifest = ArtifactManifest(
        exchange=exchange, entries=entries, aggregate_bytes=sum(e.size_bytes for e in entries)
    )
    assert manifest.has_required_success_evidence()
    assert "transcript" not in manifest.kinds()
