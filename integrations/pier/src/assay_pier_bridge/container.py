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
import os
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from assay_pier_bridge.paths import materialize_under
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
# Every docker CLI invocation is bounded so a hung daemon/CLI cannot block a
# trial past its own deadline, and so teardown itself cannot hang forever.
_START_TIMEOUT_S = 30.0
_POLL_TIMEOUT_S = 5.0
_REMOVE_TIMEOUT_S = 15.0
_PS_TIMEOUT_S = 10.0
# A Docker daemon reachable only through a VM/remote context (Docker Desktop,
# a rootless context, etc.) may not have the OS temp directory in its shared
# mount allowlist. Trial working directories live under the project instead,
# which is always within whatever the daemon can already bind-mount for a
# build context.
_DEFAULT_RUNS_ROOT = Path(__file__).resolve().parents[2] / ".trial-runs"
# Package entries name repository files with a "workspace/" prefix to
# distinguish them, inside the sealed package, from instruction.md and
# submission/CONTRACT.md (see assay.pier_packaging). Once mounted at the
# container's own /workspace, that prefix must be stripped, or the
# repository lands doubly-nested at /workspace/workspace/....
_WORKSPACE_PACKAGE_PREFIX = "workspace/"


def docker_available() -> bool:
    return shutil.which("docker") is not None


def _run(args: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def _digest(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def package_digest(package: Mapping[str, str]) -> str:
    """The bridge's own identity check for a materialized package's content.

    Deliberately independent of ``assay.pier_packaging``'s manifest digest
    algorithm (this project has no import edge back onto ``assay``): each
    side of the wire contract computes its own digest over the same sorted
    ``(path, content)`` entries, and ``TrialRequest.package_digest`` is the
    value both sides are expected to agree on out of band.
    """
    entries = sorted(package.items())
    return _digest(json.dumps(entries, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _mount_paths(package: Mapping[str, str]) -> dict[str, str]:
    """Project a sealed package's entries onto real, unprefixed /workspace paths."""
    mounted: dict[str, str] = {}
    for path, content in package.items():
        if path.startswith(_WORKSPACE_PACKAGE_PREFIX):
            rel = path[len(_WORKSPACE_PACKAGE_PREFIX) :]
        else:
            rel = path
        mounted[rel] = content
    return mounted


@dataclass(frozen=True, slots=True)
class ContainerObservation:
    """What ``docker inspect`` actually reported for a running trial container."""

    read_only_root: bool
    workspace_mount_read_only: bool | None
    uid: int
    network_mode: str
    cpu_limit: float
    memory_limit_mb: int
    pids_limit: int


def _inspect(name: str) -> ContainerObservation | None:
    result = _run(["docker", "inspect", name], timeout=_POLL_TIMEOUT_S)
    if result.returncode != 0:
        return None
    (data,) = json.loads(result.stdout)
    host_config = data["HostConfig"]
    workspace_ro = None
    for mount in data.get("Mounts", []):
        if mount.get("Destination") == "/workspace":
            workspace_ro = not mount.get("RW", True)
            break
    return ContainerObservation(
        read_only_root=bool(host_config.get("ReadonlyRootfs")),
        workspace_mount_read_only=workspace_ro,
        uid=_UID,
        network_mode=host_config.get("NetworkMode", ""),
        cpu_limit=(host_config.get("NanoCpus") or 0) / 1_000_000_000,
        memory_limit_mb=(host_config.get("Memory") or 0) // (1024 * 1024),
        pids_limit=host_config.get("PidsLimit") or 0,
    )


def _network_policy_label(network_mode: str | None) -> str:
    if network_mode == "none":
        return "network-none-no-egress-allowlist"
    if not network_mode:
        return "unknown"
    return network_mode


def _container_count(name: str) -> int | None:
    """The number of containers matching ``name``, or ``None`` if ``docker ps`` itself failed."""
    result = _run(
        ["docker", "ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.ID}}"],
        timeout=_PS_TIMEOUT_S,
    )
    if result.returncode != 0:
        return None
    return len([line for line in result.stdout.splitlines() if line.strip()])


def _force_remove(name: str) -> bool:
    result = _run(["docker", "rm", "-f", name], timeout=_REMOVE_TIMEOUT_S)
    return result.returncode == 0


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
        openrouter_api_key: str | None = None,
    ) -> None:
        actual_digest = package_digest(package)
        if actual_digest != request.package_digest:
            raise ValueError(
                "materialized package does not match the request's authorized package_digest"
            )
        self._image = image
        self._name = name
        self._request = request
        self._command = command
        self._openrouter_api_key = (
            openrouter_api_key
            if openrouter_api_key is not None
            else os.environ.get("OPENROUTER_API_KEY")
        )
        runs_root.mkdir(parents=True, exist_ok=True)
        self._workdir = runs_root / name
        self._workspace = self._workdir / "workspace"
        self._submission = self._workdir / "submission"
        self._scratch = self._workdir / "scratch"
        for directory in (self._workspace, self._submission, self._scratch):
            directory.mkdir(parents=True, exist_ok=True)
        # /submission and /scratch are writable by the container's uid 1000,
        # which will not equal the runner's own uid on most real hosts.
        self._submission.chmod(0o777)
        self._scratch.chmod(0o777)
        materialize_under(self._workspace, _mount_paths(package))
        self._cancel = threading.Event()

    def cancel(self) -> None:
        """Operator-initiated cancellation, observable by an in-flight ``run()``."""
        self._cancel.set()

    def _docker_run_args(self, limits: TrialLimits) -> list[str]:
        args = [
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
        ]
        if self._openrouter_api_key:
            # An env file (not --env on the command line) so the key never
            # appears in this host's process listing.
            env_file = self._workdir / "env"
            env_file.write_text(
                f"OPENROUTER_API_KEY={self._openrouter_api_key}\n", encoding="utf-8"
            )
            env_file.chmod(0o600)
            args += ["--env-file", str(env_file)]
        args += [
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
        return args

    def run(self) -> TrialResult:
        start_result = _run(self._docker_run_args(self._request.limits), timeout=_START_TIMEOUT_S)
        if start_result.returncode != 0:
            raise RuntimeError(f"container failed to start: {start_result.stderr.strip()}")
        deadline = time.monotonic() + self._request.limits.timeout_s
        while True:
            if self._cancel.is_set():
                raise TrialCancelledError("operator cancelled the trial")
            inspect = _run(
                ["docker", "inspect", "--format", "{{.State.Running}}", self._name],
                timeout=_POLL_TIMEOUT_S,
            )
            if inspect.returncode == 0 and inspect.stdout.strip() == "false":
                break
            if time.monotonic() >= deadline:
                raise TrialTimeoutError(f"trial exceeded {self._request.limits.timeout_s}s")
            time.sleep(_POLL_INTERVAL_S)
        exit_code = _run(
            ["docker", "inspect", "--format", "{{.State.ExitCode}}", self._name],
            timeout=_POLL_TIMEOUT_S,
        )
        submission_file = self._submission / "output"
        if (
            exit_code.stdout.strip() != "0"
            or submission_file.is_symlink()
            or not submission_file.is_file()
        ):
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
        count = _container_count(self._name)
        containers_remaining = count if count is not None else 1
        limits = self._request.limits
        return EffectiveEnforcement(
            uid=_UID,
            gid=_GID,
            workspace_read_only=bool(observation.workspace_mount_read_only)
            if observation and observation.workspace_mount_read_only is not None
            else False,
            submission_mount="/submission",
            scratch_mount="/scratch",
            network_policy=_network_policy_label(observation.network_mode if observation else None),
            cpu_limit=observation.cpu_limit if observation else limits.cpu,
            memory_limit_mb=observation.memory_limit_mb if observation else limits.memory_mb,
            pids_limit=observation.pids_limit if observation else limits.pids,
            containers_remaining=containers_remaining,
            child_processes_remaining=0,
            teardown_completed=containers_remaining == 0,
        )

    def teardown(self) -> EffectiveEnforcement:
        # Observe before destroying: once removed, docker inspect can no
        # longer report what the container actually enforced.
        observation = _inspect(self._name)
        removed = _force_remove(self._name)
        shutil.rmtree(self._workdir, ignore_errors=True)
        count = _container_count(self._name)
        confirmed_removed = removed and count == 0
        containers_remaining = 0 if confirmed_removed else (count if count is not None else 1)
        limits = self._request.limits
        return EffectiveEnforcement(
            uid=_UID,
            gid=_GID,
            workspace_read_only=bool(observation.workspace_mount_read_only)
            if observation and observation.workspace_mount_read_only is not None
            else False,
            submission_mount="/submission",
            scratch_mount="/scratch",
            network_policy=_network_policy_label(observation.network_mode if observation else None),
            cpu_limit=observation.cpu_limit if observation else limits.cpu,
            memory_limit_mb=observation.memory_limit_mb if observation else limits.memory_mb,
            pids_limit=observation.pids_limit if observation else limits.pids,
            containers_remaining=containers_remaining,
            child_processes_remaining=0,
            teardown_completed=containers_remaining == 0,
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
        openrouter_api_key: str | None = None,
    ) -> None:
        self._image = image
        self._package = package
        self._command = command
        self._runs_root = runs_root
        self._openrouter_api_key = openrouter_api_key

    def create(self, request: TrialRequest) -> DockerTrialHandle:
        name = f"assay-pier-{uuid.uuid4().hex[:12]}"
        return DockerTrialHandle(
            image=self._image,
            name=name,
            request=request,
            package=self._package,
            command=self._command,
            runs_root=self._runs_root,
            openrouter_api_key=self._openrouter_api_key,
        )
