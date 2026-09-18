"""A trial's evidence bytes must survive the handle that produced them.

``teardown`` destroys the submission mount, so bytes not carried out on the
``TrialResult`` are gone -- and the trial's own output directory is the
least trustworthy thing this project reads, so carrying them out is bounded
and refuses to follow what a model may have planted there.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from assay_pier_bridge.paths import collect_artifacts
from assay_pier_bridge.protocol import (
    MANIFEST_PATH,
    MAX_AGGREGATE_ARTIFACT_BYTES,
    MAX_ARTIFACT_BYTES,
    MAX_ARTIFACT_COUNT,
    MAX_SUBMISSION_ENTRIES,
    EffectiveEnforcement,
    TrialResult,
)
from pydantic import ValidationError


def _effective() -> EffectiveEnforcement:
    return EffectiveEnforcement(
        uid=1000,
        gid=1000,
        workspace_read_only=True,
        submission_mount="/submission",
        scratch_mount="/scratch",
        network_policy="none",
        cpu_limit=1.0,
        memory_limit_mb=512,
        pids_limit=64,
        storage_limit_mb=64,
        containers_remaining=0,
        child_processes_remaining=0,
        teardown_completed=True,
    )


def _result(**overrides: object) -> TrialResult:
    fields: dict[str, object] = {
        "cell_id": "s1:a1:w0",
        "status": "succeeded",
        "submission_ref": "sha256:" + "0" * 64,
        "effective": _effective(),
    }
    fields.update(overrides)
    return TrialResult(**fields)  # type: ignore[arg-type]


def _collect(
    root: Path,
    *,
    max_bytes: int = MAX_ARTIFACT_BYTES,
    max_aggregate_bytes: int = MAX_AGGREGATE_ARTIFACT_BYTES,
    max_entries: int = MAX_SUBMISSION_ENTRIES,
) -> dict[str, bytes]:
    return collect_artifacts(
        root,
        max_bytes=max_bytes,
        max_aggregate_bytes=max_aggregate_bytes,
        max_entries=max_entries,
        aggregate_exempt_path=MANIFEST_PATH,
    )


def test_a_result_carries_artifact_bytes() -> None:
    result = _result(artifacts={"output": b"answer = 42\n", "result.json": b"{}"})
    assert result.artifacts["output"] == b"answer = 42\n"


def test_a_result_defaults_to_no_artifacts() -> None:
    assert _result().artifacts == {}


def test_an_oversized_artifact_is_rejected_by_the_type() -> None:
    with pytest.raises(ValidationError, match="per-artifact byte limit"):
        _result(artifacts={"output": b"x" * (MAX_ARTIFACT_BYTES + 1)})


def test_an_unsafe_artifact_path_is_rejected_by_the_type() -> None:
    with pytest.raises(ValidationError, match="unsafe path"):
        _result(artifacts={"../escaped": b"x"})


def _blobs(count: int) -> dict[str, bytes]:
    return {f"declared-{index}.bin": b"\x00" * MAX_ARTIFACT_BYTES for index in range(count)}


def test_artifacts_past_the_aggregate_limit_are_rejected_by_the_type() -> None:
    artifacts = _blobs(MAX_AGGREGATE_ARTIFACT_BYTES // MAX_ARTIFACT_BYTES)
    artifacts["declared-over.bin"] = b"\x00"
    with pytest.raises(ValidationError, match="aggregate byte limit"):
        _result(artifacts=artifacts)


def test_too_many_empty_artifacts_are_rejected_by_the_type() -> None:
    artifacts = {f"empty-{index}": b"" for index in range(MAX_ARTIFACT_COUNT + 1)}
    with pytest.raises(ValidationError, match="artifact count limit"):
        _result(artifacts=artifacts)


def test_maximum_artifact_count_plus_manifest_is_accepted_by_the_type() -> None:
    artifacts = {f"empty-{index}": b"" for index in range(MAX_ARTIFACT_COUNT)}
    artifacts[MANIFEST_PATH] = b"{}"
    assert _result(artifacts=artifacts).artifacts.keys() == artifacts.keys()


def test_the_manifest_is_not_charged_to_the_aggregate_limit() -> None:
    """``MAX_AGGREGATE_ARTIFACT_BYTES`` bounds what a manifest may declare,
    and the manifest is never one of its own entries. Charging the binding
    document to the budget it bounds would fail an honest trial that filled
    the ceiling exactly, on the bytes that say what it produced."""
    artifacts = _blobs(MAX_AGGREGATE_ARTIFACT_BYTES // MAX_ARTIFACT_BYTES)
    artifacts[MANIFEST_PATH] = b'{"schema_version": "assay-pier-artifact-manifest/0.1.0"}'
    assert _result(artifacts=artifacts).artifacts[MANIFEST_PATH] == artifacts[MANIFEST_PATH]


def test_the_manifest_is_still_bounded_per_artifact() -> None:
    """Exempt from the aggregate ceiling is not exempt from every ceiling:
    what a trial can hand back stays bounded by the sum of the two."""
    with pytest.raises(ValidationError, match="per-artifact byte limit"):
        _result(artifacts={MANIFEST_PATH: b"\x00" * (MAX_ARTIFACT_BYTES + 1)})


def test_collect_artifacts_reads_regular_files_relative_to_the_root(tmp_path: Path) -> None:
    (tmp_path / "output").write_bytes(b"answer = 42\n")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "result.json").write_bytes(b'{"exit_status": "Submitted"}')
    artifacts = _collect(tmp_path)
    assert artifacts == {
        "output": b"answer = 42\n",
        "nested/result.json": b'{"exit_status": "Submitted"}',
    }


def test_collect_artifacts_never_follows_a_symlink_out_of_the_root(tmp_path: Path) -> None:
    """A model with write access to /submission can plant a symlink; reading
    through it would publish a host file as the trial's own evidence."""
    secret = tmp_path / "outside" / "secret"
    secret.parent.mkdir()
    secret.write_bytes(b"HOST SECRET")
    submission = tmp_path / "submission"
    submission.mkdir()
    (submission / "output").write_bytes(b"answer = 42\n")
    (submission / "stolen").symlink_to(secret)
    artifacts = _collect(submission)
    assert artifacts == {"output": b"answer = 42\n"}
    assert b"HOST SECRET" not in b"".join(artifacts.values())


def test_collect_artifacts_rejects_an_oversized_file_without_reading_it(tmp_path: Path) -> None:
    oversized = tmp_path / "huge"
    oversized.write_bytes(b"x" * 64)
    with pytest.raises(ValueError, match="exceeds the byte limit"):
        _collect(tmp_path, max_bytes=32)


def test_collect_artifacts_bounds_a_file_that_grows_after_lstat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    growing = tmp_path / "growing"
    growing.write_bytes(b"x" * 64)
    original_lstat = Path.lstat

    def stale_lstat(path: Path, *args: object, **kwargs: object) -> os.stat_result:
        result = original_lstat(path, *args, **kwargs)
        if path == growing:
            values = list(result)
            values[6] = 1
            return os.stat_result(values)
        return result

    monkeypatch.setattr(Path, "lstat", stale_lstat)
    with pytest.raises(ValueError, match="exceeds the byte limit"):
        _collect(tmp_path, max_bytes=32)


def test_collect_artifacts_rejects_too_many_filesystem_entries(tmp_path: Path) -> None:
    for index in range(3):
        (tmp_path / f"empty-{index}").write_bytes(b"")
    with pytest.raises(ValueError, match="filesystem entry limit"):
        _collect(tmp_path, max_entries=2)


def test_collect_artifacts_enforces_aggregate_bytes_while_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a").write_bytes(b"1234")
    (tmp_path / "b").write_bytes(b"5678")
    original_lstat = Path.lstat

    def stale_lstat(path: Path, *args: object, **kwargs: object) -> os.stat_result:
        result = original_lstat(path, *args, **kwargs)
        if path == tmp_path / "b":
            values = list(result)
            values[6] = 1
            return os.stat_result(values)
        return result

    monkeypatch.setattr(Path, "lstat", stale_lstat)
    with pytest.raises(ValueError, match="aggregate byte limit"):
        _collect(tmp_path, max_bytes=8, max_aggregate_bytes=7)


def test_collect_artifacts_skips_a_non_regular_file(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "fifo")
    (tmp_path / "output").write_bytes(b"answer = 42\n")
    assert _collect(tmp_path) == {"output": b"answer = 42\n"}
