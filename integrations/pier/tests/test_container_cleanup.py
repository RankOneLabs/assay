from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from assay_pier_bridge import container
from assay_pier_bridge.container import (
    ContainerObservation,
    DockerTrialClient,
    DockerTrialHandle,
    package_digest,
)
from assay_pier_bridge.identity import digest_bytes
from assay_pier_bridge.protocol import ModelRoute, TrialLimits, TrialRequest
from assay_pier_bridge.runtime import BridgeRuntime, TrialTimeoutError

PACKAGE = {"instruction.md": "do the thing"}
ROUTE = ModelRoute(
    endpoint="https://openrouter.ai/api/v1",
    model="anthropic/claude-3-haiku",
    provider="amazon-bedrock",
)


def _request() -> TrialRequest:
    return TrialRequest(
        cell_id="s1:a1:w0",
        package_digest=package_digest(PACKAGE),
        model_route=ROUTE,
        limits=TrialLimits(cpu=1, memory_mb=256, pids=32, timeout_s=20, storage_mb=64),
    )


def _handle(tmp_path: Path, *, name: str = "assay-pier-test") -> DockerTrialHandle:
    return DockerTrialHandle(
        image="unused@test",
        name=name,
        request=_request(),
        package=PACKAGE,
        command=["python", "-m", "assay_pier_bridge"],
        runs_root=tmp_path,
    )


def _completed(
    args: list[str], *, stdout: str = "", returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr="")


def _fake_successful_run(args: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    if args[:2] == ["docker", "run"]:
        return _completed(args, stdout="container-id\n")
    if args[:4] == ["docker", "inspect", "--format", "{{.State.Running}}"]:
        return _completed(args, stdout="false\n")
    if args[:4] == ["docker", "inspect", "--format", "{{.State.ExitCode}}"]:
        return _completed(args, stdout="0\n")
    raise AssertionError(f"unexpected docker invocation: {args}")


@pytest.mark.parametrize("inspection_error", [subprocess.TimeoutExpired("docker", 1), ValueError()])
def test_inspection_failure_still_removes_and_cleans_the_workdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, inspection_error: Exception
) -> None:
    handle = _handle(tmp_path)
    removed: list[str] = []

    def failed_inspection(name: str) -> None:
        raise inspection_error

    monkeypatch.setattr(container, "_inspect", failed_inspection)
    monkeypatch.setattr(container, "_force_remove", lambda name: removed.append(name) or True)
    monkeypatch.setattr(container, "_container_count", lambda name: 0)

    effective = handle.teardown()

    assert removed == ["assay-pier-test"]
    assert not (tmp_path / "assay-pier-test").exists()
    assert effective.teardown_completed is True
    assert effective.network_policy == "unknown"


def test_semantically_invalid_observation_cannot_break_the_cleanup_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle = _handle(tmp_path)
    malformed = ContainerObservation(
        read_only_root=False,
        workspace_mount_read_only=None,
        uid=1000,
        network_mode="",
        cpu_limit=0,
        memory_limit_mb=0,
        pids_limit=0,
        storage_limit_mb=0,
    )
    monkeypatch.setattr(container, "_inspect", lambda name: malformed)
    monkeypatch.setattr(container, "_force_remove", lambda name: True)
    monkeypatch.setattr(container, "_container_count", lambda name: 0)

    effective = handle.teardown()

    assert effective.teardown_completed is True
    assert effective.cpu_limit == _request().limits.cpu
    assert effective.memory_limit_mb == _request().limits.memory_mb


def test_removal_timeout_still_checks_count_and_reports_uncertainty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle = _handle(tmp_path)
    counted: list[str] = []
    monkeypatch.setattr(container, "_inspect", lambda name: None)

    def timed_out_removal(name: str) -> bool:
        raise subprocess.TimeoutExpired("docker rm", 1)

    monkeypatch.setattr(container, "_force_remove", timed_out_removal)
    monkeypatch.setattr(container, "_container_count", lambda name: counted.append(name) or None)

    effective = handle.teardown()

    assert counted == ["assay-pier-test"]
    assert effective.containers_remaining == 1
    assert effective.teardown_completed is False


def test_an_already_absent_container_is_a_completed_repeat_teardown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle = _handle(tmp_path)
    monkeypatch.setattr(container, "_inspect", lambda name: None)
    monkeypatch.setattr(container, "_force_remove", lambda name: False)
    monkeypatch.setattr(container, "_container_count", lambda name: 0)

    assert handle.teardown().teardown_completed is True
    assert handle.teardown().teardown_completed is True


def test_runtime_preserves_timeout_when_teardown_inspection_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    removed: list[str] = []

    def timed_out_run(self: DockerTrialHandle) -> None:
        raise TrialTimeoutError("original timeout")

    def failed_inspection(name: str) -> None:
        raise subprocess.TimeoutExpired("docker inspect", 1)

    monkeypatch.setattr(DockerTrialHandle, "run", timed_out_run)
    monkeypatch.setattr(container, "_inspect", failed_inspection)
    monkeypatch.setattr(container, "_force_remove", lambda name: removed.append(name) or True)
    monkeypatch.setattr(container, "_container_count", lambda name: 0)
    runtime = BridgeRuntime(
        DockerTrialClient(
            image="unused@test",
            package=PACKAGE,
            command=["python", "-m", "assay_pier_bridge"],
            runs_root=tmp_path,
        )
    )

    result = runtime.run_cell(_request())

    assert result.status == "timeout"
    assert result.error_type == "TrialTimeoutError"
    assert result.error_message == "original timeout"
    assert len(removed) == 1


def test_driver_hashes_the_exact_bounded_output_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle = _handle(tmp_path)
    output = "ünicode\r\n".encode()
    (tmp_path / "assay-pier-test" / "submission" / "output").write_bytes(output)
    monkeypatch.setattr(container, "_run", _fake_successful_run)
    monkeypatch.setattr(container, "_inspect", lambda name: None)
    monkeypatch.setattr(container, "_container_count", lambda name: 1)

    result = handle.run()

    assert result.artifacts["output"] == output
    assert result.submission_ref == digest_bytes(output)


def test_driver_rejects_output_that_exceeds_the_collection_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle = _handle(tmp_path)
    (tmp_path / "assay-pier-test" / "submission" / "output").write_bytes(b"12345")
    monkeypatch.setattr(container, "MAX_ARTIFACT_BYTES", 4)
    monkeypatch.setattr(container, "_run", _fake_successful_run)

    with pytest.raises(ValueError, match="byte limit"):
        handle.run()
