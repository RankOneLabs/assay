from __future__ import annotations

import pytest
from pydantic import ValidationError

from assay.models import CellCoordinate
from assay.pier_protocol import (
    ArtifactEntry,
    ArtifactManifest,
    ManifestRejected,
    PierExchange,
    RuntimeBinding,
    bind_exchange,
    bridge_reports_failure,
    reject_on_binding_mismatch,
    trial_name_for,
    verify_artifact_bytes,
)


def _coordinate(**overrides: object) -> CellCoordinate:
    fields = {
        "subject_id": "s1",
        "arm_id": "a1",
        "worker_repeat": 0,
        "realization_ref": "sha256:" + "0" * 64,
    }
    fields.update(overrides)
    return CellCoordinate(**fields)  # type: ignore[arg-type]


def _binding(**overrides: object) -> RuntimeBinding:
    fields = {
        "runtime_version": "lock-v1",
        "image_digest": "sha256:" + "1" * 64,
        "configuration_ref": "sha256:" + "2" * 64,
        "package_digest": "sha256:" + "3" * 64,
    }
    fields.update(overrides)
    return RuntimeBinding(**fields)  # type: ignore[arg-type]


def test_trial_name_matches_dashed_cell_id() -> None:
    coordinate = _coordinate()
    assert trial_name_for(coordinate) == "s1-a1-w0"
    exchange = bind_exchange(coordinate=coordinate, binding=_binding())
    assert exchange.trial_name == "s1-a1-w0"


def test_exchange_rejects_a_mismatched_trial_name() -> None:
    with pytest.raises(ValidationError, match="trial name"):
        PierExchange(coordinate=_coordinate(), binding=_binding(), trial_name="wrong-name")


def test_binding_mismatch_is_rejected() -> None:
    with pytest.raises(ManifestRejected, match="binding"):
        reject_on_binding_mismatch(_binding(), _binding(package_digest="sha256:" + "9" * 64))


def test_binding_match_is_accepted() -> None:
    reject_on_binding_mismatch(_binding(), _binding())


@pytest.mark.parametrize(
    ("status", "submission_ref", "error_type", "mini_exit_status", "expected"),
    [
        ("succeeded", "sha256:" + "0" * 64, None, "Submitted", False),
        ("succeeded", "sha256:" + "0" * 64, None, "LimitsExceeded", True),
        ("succeeded", "sha256:" + "0" * 64, None, None, True),
        ("succeeded", None, None, "Submitted", True),
        ("succeeded", "sha256:" + "0" * 64, "SomeError", "Submitted", True),
        ("failed", None, "SomeError", "Submitted", True),
        ("timeout", None, "TrialTimeoutError", "Submitted", True),
        ("cancelled", None, "TrialCancelledError", "Submitted", True),
    ],
)
def test_bridge_reports_failure(
    status: str,
    submission_ref: str | None,
    error_type: str | None,
    mini_exit_status: str | None,
    expected: bool,
) -> None:
    actual = bridge_reports_failure(
        status=status,
        submission_ref=submission_ref,
        error_type=error_type,
        mini_exit_status=mini_exit_status,
    )
    assert actual is expected


def test_mini_exit_status_from_result_bytes_extracts_top_level_field() -> None:
    from assay.pier_protocol import mini_exit_status_from_result_bytes

    assert mini_exit_status_from_result_bytes(b'{"exit_status": "Submitted"}') == "Submitted"


@pytest.mark.parametrize(
    "raw",
    [None, b"not json", b'{"no_exit_status": true}', b"[]", b"\xff\xfe", b'{"exit_status": 1}'],
)
def test_mini_exit_status_from_result_bytes_is_none_on_anything_malformed(
    raw: bytes | None,
) -> None:
    from assay.pier_protocol import mini_exit_status_from_result_bytes

    assert mini_exit_status_from_result_bytes(raw) is None


def _entry(path: str, data: bytes, kind: str = "candidate", utf8: bool = True) -> ArtifactEntry:
    from assay.canonical import digest_bytes

    return ArtifactEntry(
        path=path, kind=kind, size_bytes=len(data), checksum=digest_bytes(data), utf8=utf8
    )  # type: ignore[arg-type]


def test_manifest_rejects_duplicate_paths() -> None:
    exchange = bind_exchange(coordinate=_coordinate(), binding=_binding())
    entry = _entry("candidate.txt", b"hi")
    with pytest.raises(ValidationError, match="duplicate artifact path"):
        ArtifactManifest(exchange=exchange, entries=(entry, entry), aggregate_bytes=4)


def test_manifest_rejects_aggregate_mismatch() -> None:
    exchange = bind_exchange(coordinate=_coordinate(), binding=_binding())
    entry = _entry("candidate.txt", b"hi")
    with pytest.raises(ValidationError, match="aggregate_bytes"):
        ArtifactManifest(exchange=exchange, entries=(entry,), aggregate_bytes=999)


def test_manifest_rejects_unsafe_path() -> None:
    with pytest.raises(ValidationError, match="unsafe"):
        _entry("../escape.txt", b"hi")


def test_verify_artifact_bytes_accepts_matching_content() -> None:
    exchange = bind_exchange(coordinate=_coordinate(), binding=_binding())
    data = b"the candidate"
    entry = _entry("candidate.txt", data)
    manifest = ArtifactManifest(exchange=exchange, entries=(entry,), aggregate_bytes=len(data))
    verify_artifact_bytes(manifest, artifact_bytes={"candidate.txt": data})


def test_verify_artifact_bytes_rejects_missing_artifact() -> None:
    exchange = bind_exchange(coordinate=_coordinate(), binding=_binding())
    data = b"the candidate"
    entry = _entry("candidate.txt", data)
    manifest = ArtifactManifest(exchange=exchange, entries=(entry,), aggregate_bytes=len(data))
    with pytest.raises(ManifestRejected, match="missing"):
        verify_artifact_bytes(manifest, artifact_bytes={})


def test_verify_artifact_bytes_rejects_size_mismatch() -> None:
    exchange = bind_exchange(coordinate=_coordinate(), binding=_binding())
    entry = _entry("candidate.txt", b"the candidate")
    manifest = ArtifactManifest(
        exchange=exchange, entries=(entry,), aggregate_bytes=entry.size_bytes
    )
    with pytest.raises(ManifestRejected, match="size mismatch"):
        verify_artifact_bytes(manifest, artifact_bytes={"candidate.txt": b"short"})


def test_verify_artifact_bytes_rejects_checksum_mismatch() -> None:
    exchange = bind_exchange(coordinate=_coordinate(), binding=_binding())
    data = b"the candidate"
    entry = _entry("candidate.txt", data)
    manifest = ArtifactManifest(exchange=exchange, entries=(entry,), aggregate_bytes=len(data))
    forged = b"x" * len(data)
    with pytest.raises(ManifestRejected, match="checksum mismatch"):
        verify_artifact_bytes(manifest, artifact_bytes={"candidate.txt": forged})


def test_verify_artifact_bytes_rejects_non_utf8_when_declared_utf8() -> None:
    exchange = bind_exchange(coordinate=_coordinate(), binding=_binding())
    data = b"\xff\xfe\x00\x01"
    entry = _entry("candidate.txt", data)
    manifest = ArtifactManifest(exchange=exchange, entries=(entry,), aggregate_bytes=len(data))
    with pytest.raises(ManifestRejected, match="UTF-8"):
        verify_artifact_bytes(manifest, artifact_bytes={"candidate.txt": data})


def test_manifest_reports_required_success_kinds() -> None:
    exchange = bind_exchange(coordinate=_coordinate(), binding=_binding())
    kinds = ["raw_trajectory", "candidate", "result", "configuration", "manifest"]
    entries = tuple(
        _entry(f"{kind}.json", f'{{"kind": "{kind}"}}'.encode(), kind=kind) for kind in kinds
    )
    manifest = ArtifactManifest(
        exchange=exchange, entries=entries, aggregate_bytes=sum(e.size_bytes for e in entries)
    )
    assert manifest.has_required_success_evidence()


def test_manifest_missing_required_kind_is_reported() -> None:
    exchange = bind_exchange(coordinate=_coordinate(), binding=_binding())
    entries = (_entry("candidate.json", b"{}", kind="candidate"),)
    manifest = ArtifactManifest(exchange=exchange, entries=entries, aggregate_bytes=2)
    assert not manifest.has_required_success_evidence()
