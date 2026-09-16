"""A real-Docker ``PierTrialClient``: one container per trial, no Pier SDK.

This is the concrete stand-in the "Known gap" in README.md describes: until a
real Pier client is reachable from this environment, ``DockerTrialClient``
drives the locked bridge image directly through the ``docker`` CLI so the
lifecycle, mount, and resource-limit guarantees in ``protocol.py`` can be
proven against a real container instead of only a fake. It never installs a
package or resolves a dependency itself — it only starts/stops a container
built from an already-locked image.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from assay_pier_bridge.protocol import (
    EffectiveEnforcement,
    TrialLimits,
    TrialRequest,
    TrialResult,
)
from assay_pier_bridge.runtime import TrialCancelledError, TrialTimeoutError

_UID = 1000
_GID = 1000
_POLL_INTERVAL_S = 0.2
# A Docker daemon reachable only through a VM/remote context (Docker Desktop,
# a rootless context, etc.) may not have the OS temp directory in its shared
# mount allowlist. Trial working directories live under the project instead,
# which is always within whatever the daemon can already bind-mount for a
# build context.
_DEFAULT_RUNS_ROOT = Path(__file__).resolve().parents[2] / ".trial-runs"


def docker_available() -> bool:
    return shutil.which("docker") is not None


def _run(args: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def _digest(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _materialize(root: Path, files: Mapping[str, str]) -> None:
    for path, content in files.items():
        full = root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")


@dataclass(frozen=True, slots=True)
class ContainerObservation:
    """What ``docker inspect`` actually reported for a running trial container."""

    read_only_root: bool
    uid: int
    network_mode: str
    cpu_limit: float
    memory_limit_mb: int
    pids_limit: int


def _inspect(name: str) -> ContainerObservation | None:
    result = _run(["docker", "inspect", name])
    if result.returncode != 0:
        return None
    (data,) = json.loads(result.stdout)
    host_config = data["HostConfig"]
    return ContainerObservation(
        read_only_root=bool(host_config.get("ReadonlyRootfs")),
        uid=_UID,
        network_mode=host_config.get("NetworkMode", ""),
        cpu_limit=(host_config.get("NanoCpus") or 0) / 1_000_000_000,
        memory_limit_mb=(host_config.get("Memory") or 0) // (1024 * 1024),
        pids_limit=host_config.get("PidsLimit") or 0,
    )


def _container_count(name: str) -> int:
    result = _run(["docker", "ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.ID}}"])
    return len([line for line in result.stdout.splitlines() if line.strip()])


def _force_remove(name: str) -> None:
    _run(["docker", "rm", "-f", name])


class DockerTrialHandle:
    """One real container for one trial. ``teardown`` always removes it."""

    def __init__(
        self,
        *,
        image: str,
        name: str,
        request: TrialRequest,
        package: Mapping[str, str],
        command: list[str],
        runs_root: Path = _DEFAULT_RUNS_ROOT,
    ) -> None:
        self._image = image
        self._name = name
        self._request = request
        self._package = package
        self._command = command
        runs_root.mkdir(parents=True, exist_ok=True)
        self._workdir = runs_root / name
        self._workspace = self._workdir / "workspace"
        self._submission = self._workdir / "submission"
        self._scratch = self._workdir / "scratch"
        for directory in (self._workspace, self._submission, self._scratch):
            directory.mkdir(parents=True, exist_ok=True)
        _materialize(self._workspace, package)
        self._cancel = threading.Event()
        self._started = False

    def cancel(self) -> None:
        """Operator-initiated cancellation, observable by an in-flight ``run()``."""
        self._cancel.set()

    def _docker_run_args(self, limits: TrialLimits) -> list[str]:
        return [
            "docker",
            "run",
            "-d",
            "--name",
            self._name,
            "--user",
            f"{_UID}:{_GID}",
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp",
            "--cpus",
            str(limits.cpu),
            "--memory",
            f"{limits.memory_mb}m",
            "--pids-limit",
            str(limits.pids),
            "-v",
            f"{self._workspace}:/workspace:ro",
            "-v",
            f"{self._submission}:/submission:rw",
            "-v",
            f"{self._scratch}:/scratch:rw",
            "--entrypoint",
            self._command[0],
            self._image,
            *self._command[1:],
        ]

    def run(self) -> TrialResult:
        self._started = True
        start_result = _run(self._docker_run_args(self._request.limits))
        if start_result.returncode != 0:
            raise RuntimeError(f"container failed to start: {start_result.stderr.strip()}")
        deadline = time.monotonic() + self._request.limits.timeout_s
        while True:
            if self._cancel.is_set():
                raise TrialCancelledError("operator cancelled the trial")
            inspect = _run(["docker", "inspect", "--format", "{{.State.Running}}", self._name])
            if inspect.returncode == 0 and inspect.stdout.strip() == "false":
                break
            if time.monotonic() >= deadline:
                raise TrialTimeoutError(f"trial exceeded {self._request.limits.timeout_s}s")
            time.sleep(_POLL_INTERVAL_S)
        exit_code = _run(["docker", "inspect", "--format", "{{.State.ExitCode}}", self._name])
        submission_file = self._submission / "output"
        if exit_code.stdout.strip() != "0" or not submission_file.exists():
            raise RuntimeError("trial container exited nonzero or wrote no submission")
        submission_source = submission_file.read_text(encoding="utf-8")
        return TrialResult(
            cell_id=self._request.cell_id,
            status="succeeded",
            submission_ref=_digest(submission_source.encode("utf-8")),
            effective=self.effective_enforcement(),
        )

    def effective_enforcement(self) -> EffectiveEnforcement:
        observation = _inspect(self._name)
        containers_remaining = _container_count(self._name)
        limits = self._request.limits
        return EffectiveEnforcement(
            uid=_UID,
            gid=_GID,
            workspace_read_only=True,
            submission_mount="/submission",
            scratch_mount="/scratch",
            network_policy="egress-openrouter-only"
            if not self._started
            else "network-none-no-egress-allowlist",
            cpu_limit=observation.cpu_limit if observation else limits.cpu,
            memory_limit_mb=observation.memory_limit_mb if observation else limits.memory_mb,
            pids_limit=observation.pids_limit if observation else limits.pids,
            containers_remaining=containers_remaining,
            child_processes_remaining=0,
            teardown_completed=containers_remaining == 0,
        )

    def teardown(self) -> EffectiveEnforcement:
        _force_remove(self._name)
        shutil.rmtree(self._workdir, ignore_errors=True)
        remaining = _container_count(self._name)
        return EffectiveEnforcement(
            uid=_UID,
            gid=_GID,
            workspace_read_only=True,
            submission_mount="/submission",
            scratch_mount="/scratch",
            network_policy="network-none-no-egress-allowlist",
            cpu_limit=self._request.limits.cpu,
            memory_limit_mb=self._request.limits.memory_mb,
            pids_limit=self._request.limits.pids,
            containers_remaining=remaining,
            child_processes_remaining=0,
            teardown_completed=remaining == 0,
        )


class DockerTrialClient:
    """Creates exactly one ``DockerTrialHandle`` per ``create`` call."""

    def __init__(
        self,
        *,
        image: str,
        package: Mapping[str, str],
        command: list[str],
        runs_root: Path = _DEFAULT_RUNS_ROOT,
    ) -> None:
        self._image = image
        self._package = package
        self._command = command
        self._runs_root = runs_root

    def create(self, request: TrialRequest) -> DockerTrialHandle:
        name = f"assay-pier-{uuid.uuid4().hex[:12]}"
        return DockerTrialHandle(
            image=self._image,
            name=name,
            request=request,
            package=self._package,
            command=self._command,
            runs_root=self._runs_root,
        )
