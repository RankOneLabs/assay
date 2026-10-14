from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from assay_pier_bridge import container
from assay_pier_bridge.container import (
    ContainerObservation,
    DockerTrialClient,
    DockerTrialHandle,
    MemoryLimitExceededError,
    StorageExhaustedError,
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
    assert effective.cpu_limit == 0
    assert effective.memory_limit_mb == 0


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
    monkeypatch.setattr(
        DockerTrialHandle, "_prepare_quota", lambda self, limits: self._scratch.mkdir()
    )
    monkeypatch.setattr(DockerTrialHandle, "_assert_enforcement", lambda self, observation: None)
    monkeypatch.setattr(
        container,
        "_inspect",
        lambda name: ContainerObservation(
            read_only_root=True,
            workspace_mount_read_only=True,
            uid=1000,
            network_mode="none",
            cpu_limit=1,
            memory_limit_mb=256,
            pids_limit=32,
            storage_limit_mb=64,
        ),
    )
    monkeypatch.setattr(container, "_container_count", lambda name: 1)

    result = handle.run()

    assert result.artifacts["output"] == output
    assert result.submission_ref == digest_bytes(output)


@pytest.mark.parametrize(
    ("exit_code", "log", "raises_storage"),
    [
        (0, "", False),
        (1, "dd: error writing '/scratch/big': No space left on device", True),
        (1, "dd: error writing '/tmp/big': No space left on device", False),
        (1, "permission denied", False),
    ],
)
def test_storage_cause_requires_trial_enospc_not_a_full_host_filesystem(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exit_code: int,
    log: str,
    raises_storage: bool,
) -> None:
    handle = _handle(tmp_path)
    (tmp_path / "assay-pier-test" / "submission" / "output").write_text("answer")
    observed = ContainerObservation(
        read_only_root=True,
        workspace_mount_read_only=True,
        uid=1000,
        network_mode="none",
        cpu_limit=1,
        memory_limit_mb=256,
        pids_limit=32,
        storage_limit_mb=64,
    )

    def trial_run(args: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
        if args[:4] == ["docker", "inspect", "--format", "{{.State.ExitCode}}"]:
            return _completed(args, stdout=f"{exit_code}\n")
        if args[:2] == ["docker", "logs"]:
            return _completed(args, stdout=log)
        return _fake_successful_run(args, timeout=timeout)

    monkeypatch.setattr(container, "_run", trial_run)
    monkeypatch.setattr(DockerTrialHandle, "_prepare_quota", lambda self, limits: None)
    monkeypatch.setattr(DockerTrialHandle, "_assert_enforcement", lambda self, observation: None)
    monkeypatch.setattr(container, "_inspect", lambda name: observed)
    monkeypatch.setattr(container, "_container_count", lambda name: 1)
    if raises_storage:
        with pytest.raises(StorageExhaustedError):
            handle.run()
    elif exit_code:
        with pytest.raises(RuntimeError, match="exited nonzero"):
            handle.run()
    else:
        # A trial may fill its quota exactly and exit cleanly.
        assert handle.run().status == "succeeded"


@pytest.mark.parametrize(
    ("exit_code", "log", "oom_killed"),
    [(137, "", True), (1, "MemoryError", False), (137, "", False)],
)
def test_memory_failure_is_distinct_from_storage_exhaustion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exit_code: int,
    log: str,
    oom_killed: bool,
) -> None:
    handle = _handle(tmp_path)
    observed = ContainerObservation(
        read_only_root=True,
        workspace_mount_read_only=True,
        uid=1000,
        network_mode="none",
        cpu_limit=1,
        memory_limit_mb=256,
        pids_limit=32,
        storage_limit_mb=64,
        oom_killed=oom_killed,
    )

    def trial_run(args: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
        if args[:4] == ["docker", "inspect", "--format", "{{.State.ExitCode}}"]:
            return _completed(args, stdout=f"{exit_code}\n")
        if args[:2] == ["docker", "logs"]:
            return _completed(args, stdout=log)
        return _fake_successful_run(args, timeout=timeout)

    monkeypatch.setattr(container, "_run", trial_run)
    monkeypatch.setattr(DockerTrialHandle, "_prepare_quota", lambda self, limits: None)
    monkeypatch.setattr(DockerTrialHandle, "_assert_enforcement", lambda self, observation: None)
    monkeypatch.setattr(container, "_inspect", lambda name: observed)
    if oom_killed or "MemoryError" in log:
        with pytest.raises(MemoryLimitExceededError):
            handle.run()
    else:
        with pytest.raises(RuntimeError, match="exited nonzero"):
            handle.run()


@pytest.mark.parametrize(
    ("failed_command", "raises"),
    [("iptables", False), ("iptables", True), ("network", False), ("umount", False)],
)
def test_teardown_retries_failed_host_cleanup_and_reports_residue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_command: str,
    raises: bool,
) -> None:
    handle = _handle(tmp_path)
    handle._firewall_installed = [("INPUT", ["-j", "DROP"])]
    handle._network_created = True
    handle._quota_mounted = True
    attempts: dict[str, int] = {"iptables": 0, "network": 0, "umount": 0}

    def host_run(args: list[str]) -> subprocess.CompletedProcess[str]:
        command = args[0]
        attempts[command] += 1
        if command == failed_command and attempts[command] == 1:
            if raises:
                raise subprocess.TimeoutExpired(args, 1)
            return _completed(args, returncode=1)
        return _completed(args)

    def docker_run(args: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
        assert args[:3] == ["docker", "network", "rm"]
        attempts["network"] += 1
        return _completed(
            args,
            returncode=1 if failed_command == "network" and attempts["network"] == 1 else 0,
        )

    monkeypatch.setattr(container, "_inspect", lambda name: None)
    monkeypatch.setattr(container, "_force_remove", lambda name: True)
    monkeypatch.setattr(container, "_container_count", lambda name: 0)
    monkeypatch.setattr(container, "_host_run", host_run)
    monkeypatch.setattr(container, "_run", docker_run)

    first = handle.teardown()
    assert first.containers_remaining == 0
    assert first.teardown_completed is False
    assert bool(handle._firewall_installed) is (failed_command == "iptables")
    assert handle._network_created is (failed_command == "network")
    assert handle._quota_mounted is (failed_command == "umount")
    assert handle._workdir.exists() is (failed_command == "umount")

    second = handle.teardown()
    assert second.teardown_completed is True
    assert handle._firewall_installed == []
    assert handle._network_created is False
    assert handle._quota_mounted is False
    assert not handle._workdir.exists()
    assert attempts == {command: 2 if command == failed_command else 1 for command in attempts}


def test_driver_rejects_output_that_exceeds_the_collection_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle = _handle(tmp_path)
    (tmp_path / "assay-pier-test" / "submission" / "output").write_bytes(b"12345")
    monkeypatch.setattr(container, "MAX_ARTIFACT_BYTES", 4)
    monkeypatch.setattr(container, "_run", _fake_successful_run)
    monkeypatch.setattr(
        DockerTrialHandle, "_prepare_quota", lambda self, limits: self._scratch.mkdir()
    )
    monkeypatch.setattr(DockerTrialHandle, "_assert_enforcement", lambda self, observation: None)
    monkeypatch.setattr(
        container,
        "_inspect",
        lambda name: ContainerObservation(
            read_only_root=True,
            workspace_mount_read_only=True,
            uid=1000,
            network_mode="none",
            cpu_limit=1,
            memory_limit_mb=256,
            pids_limit=32,
            storage_limit_mb=64,
        ),
    )

    with pytest.raises(ValueError, match="byte limit"):
        handle.run()
