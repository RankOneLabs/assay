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

import contextlib
import json
import os
import shlex
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from assay_pier_bridge.evidence import worker_usage_from_result_bytes
from assay_pier_bridge.identity import canonical_json
from assay_pier_bridge.identity import digest_bytes as _digest
from assay_pier_bridge.identity import package_digest as package_digest
from assay_pier_bridge.paths import (
    ArtifactCollectionRejected,
    collect_artifacts,
    materialize_under,
    regular_tree,
    safe_relative_path,
    submission_patch,
)
from assay_pier_bridge.protocol import (
    MANIFEST_PATH,
    MAX_AGGREGATE_ARTIFACT_BYTES,
    MAX_ARTIFACT_BYTES,
    MAX_SUBMISSION_ENTRIES,
    CandidateSubmission,
    EffectiveEnforcement,
    TrialLimits,
    TrialRequest,
    TrialResult,
)
from assay_pier_bridge.runtime import (
    CandidateTrialError,
    InfrastructureTrialError,
    TrialCancelledError,
    TrialTimeoutError,
    seal_observed_artifacts,
)

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


def _mount_paths(package: Mapping[str, str]) -> dict[str, str]:
    """Project a sealed package's entries onto real, unprefixed /workspace paths.

    Stripping the prefix can make the projection non-injective: a repository
    that contains a file named ``instruction.md`` is packaged as
    ``workspace/instruction.md`` and lands on the same mounted path as the
    sealed ``instruction.md``. Silently keeping one of them would let a
    repository replace the instruction the model is given -- and since the
    package arrives sorted, it is the repository file that wins. A collision
    is a terminal error here, not a merge. ``assay``'s ``gate_package``
    rejects the same packages before dispatch; this side repeats the check
    because the bridge must not depend on any particular producer having run
    it (the two projects share no import edge -- see ``README.md``). Paths
    must also use their canonical POSIX spelling before comparison: otherwise
    raw keys such as ``instruction.md`` and ``./instruction.md`` look distinct
    here but name the same file when materialized.
    """
    mounted: dict[str, str] = {}
    origin: dict[str, str] = {}
    for path, content in package.items():
        safe_relative_path(path)
        if path.startswith(_WORKSPACE_PACKAGE_PREFIX):
            rel = path[len(_WORKSPACE_PACKAGE_PREFIX) :]
        else:
            rel = path
        mounted_path = safe_relative_path(rel).as_posix()
        if mounted_path in mounted:
            raise ValueError(
                f"package entries {origin[mounted_path]!r} and {path!r} collide at the "
                f"mounted path {mounted_path!r}"
            )
        origin[mounted_path] = path
        mounted[mounted_path] = content
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
    storage_limit_mb: int
    gid: int = 1000
    scratch_mount_kind: str = "unknown"
    scratch_source: str | None = None
    scratch_tmpfs: bool = False
    oom_killed: bool = False
    network_policy_label: str = "unknown"


def _usable_observation(observation: ContainerObservation | None) -> ContainerObservation | None:
    """Reject partial/malformed observations before they reach the strict result model."""
    if observation is None:
        return None
    positive_ints = (
        observation.memory_limit_mb,
        observation.pids_limit,
    )
    if (
        isinstance(observation.cpu_limit, bool)
        or not isinstance(observation.cpu_limit, (int, float))
        or observation.cpu_limit <= 0
        or any(type(value) is not int or value <= 0 for value in positive_ints)
        or not isinstance(observation.network_mode, str)
        or not isinstance(observation.workspace_mount_read_only, (bool, type(None)))
        or type(observation.uid) is not int
        or type(observation.gid) is not int
        or observation.uid <= 0
        or observation.gid <= 0
    ):
        return None
    return observation


def _quota_mb(source: str | None) -> int:
    """Read the loop device capacity backing Docker's inspected bind source."""
    if source is None or not os.path.ismount(source):
        return 0
    device = os.stat(source).st_dev
    sys_device = Path(f"/sys/dev/block/{os.major(device)}:{os.minor(device)}")
    # A plain host directory would otherwise report the capacity of its
    # containing filesystem and pretend to have the requested per-trial quota.
    if not (sys_device / "loop" / "backing_file").is_file():
        return 0
    size_bytes = int((sys_device / "size").read_text(encoding="ascii")) * 512
    return size_bytes // (1024 * 1024) if size_bytes % (1024 * 1024) == 0 else 0


def _inspect(name: str, *, timeout: float = _POLL_TIMEOUT_S) -> ContainerObservation | None:
    result = _run(["docker", "inspect", name], timeout=timeout)
    if result.returncode != 0:
        return None
    (data,) = json.loads(result.stdout)
    host_config = data["HostConfig"]
    workspace_ro = None
    scratch_kind = "missing"
    scratch_source = None
    for mount in data.get("Mounts", []):
        if mount.get("Destination") == "/workspace":
            workspace_ro = not mount.get("RW", True)
        if mount.get("Destination") == "/scratch":
            scratch_kind = mount.get("Type", "unknown")
            scratch_source = mount.get("Source")
    tmpfs = host_config.get("Tmpfs")
    scratch_tmpfs = isinstance(tmpfs, Mapping) and "/scratch" in tmpfs
    storage_mb = _quota_mb(scratch_source) if scratch_kind == "bind" else 0
    user = str(data.get("Config", {}).get("User", ""))
    uid = int(user.split(":", 1)[0]) if user.split(":", 1)[0].isdigit() else 0
    gid_part = user.split(":", 1)[1] if ":" in user else ""
    gid = int(gid_part) if gid_part.isdigit() else 0
    return ContainerObservation(
        read_only_root=bool(host_config.get("ReadonlyRootfs")),
        workspace_mount_read_only=workspace_ro,
        uid=uid,
        gid=gid,
        network_mode=host_config.get("NetworkMode", ""),
        cpu_limit=(host_config.get("NanoCpus") or 0) / 1_000_000_000,
        memory_limit_mb=(host_config.get("Memory") or 0) // (1024 * 1024),
        pids_limit=host_config.get("PidsLimit") or 0,
        storage_limit_mb=storage_mb,
        scratch_mount_kind=scratch_kind,
        scratch_source=scratch_source,
        scratch_tmpfs=scratch_tmpfs,
        oom_killed=bool(data.get("State", {}).get("OOMKilled", False)),
        network_policy_label=_network_policy_label(host_config.get("NetworkMode", "")),
    )


def _network_policy_label(network_mode: str | None) -> str:
    if network_mode == "none":
        return "network-none-no-egress-allowlist"
    if not network_mode:
        return "unknown"
    result = _run(["docker", "network", "inspect", network_mode], timeout=_POLL_TIMEOUT_S)
    if result.returncode != 0:
        return "unknown"
    try:
        (network,) = json.loads(result.stdout)
        options = network["Options"]
        labels = network["Labels"]
        interface = options["com.docker.network.bridge.name"]
        host = labels["assay.egress.host"]
        port = labels["assay.egress.port"]
        if network["Driver"] != "bridge" or network.get("EnableIPv6") or network.get("Internal"):
            return "unknown"
        for chain in ("INPUT", "FORWARD"):
            rules = _host_run(["iptables", "-S", chain])
            if rules.returncode != 0:
                return "unknown"
            observed = [_firewall_rule_fields(line, chain) for line in rules.stdout.splitlines()]
            allow = sorted(
                (
                    ("-i", interface),
                    ("-p", "tcp"),
                    ("-d", host),
                    ("--dport", str(int(port))),
                    ("-j", "ACCEPT"),
                )
            )
            deny = sorted((("-i", interface), ("-j", "DROP")))
            if allow not in observed or deny not in observed:
                return "unknown"
            if observed.index(allow) >= observed.index(deny):
                return "unknown"
    except (KeyError, ValueError, TypeError, IndexError, OSError):
        return "unknown"
    return f"egress-lan-host-port:{host}:{port}"


def _firewall_rule_fields(line: str, chain: str) -> list[tuple[str, str]] | None:
    """Normalize iptables -S flag order without losing rule order in the chain."""
    tokens = shlex.split(line)
    if tokens[:2] != ["-A", chain] or len(tokens[2:]) % 2:
        return None
    fields = []
    for flag, value in zip(tokens[2::2], tokens[3::2], strict=True):
        if (flag, value) == ("-m", "tcp"):
            continue
        if flag == "-d" and value.endswith("/32"):
            value = value[:-3]
        fields.append((flag, value))
    return sorted(fields)


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


def _host_run(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Host mount/firewall operations require root; fail closed without noninteractive sudo."""
    command = args if os.geteuid() == 0 else ["sudo", "-n", *args]
    return _run(command, timeout=_START_TIMEOUT_S)


def _checked_host(args: list[str]) -> None:
    result = _host_run(args)
    if result.returncode != 0:
        raise InfrastructureTrialError(
            "enforcement", f"host envelope setup failed: {args[0]}: {result.stderr.strip()}"
        )


def _firewall_rules(host: str, port: int) -> list[tuple[str, list[str]]]:
    return [
        (chain, rule)
        for chain in ("INPUT", "FORWARD")
        for rule in (
            ["-p", "tcp", "-d", host, "--dport", str(port), "-j", "ACCEPT"],
            ["-j", "DROP"],
        )
    ]


class MountKindMismatchError(InfrastructureTrialError):
    def __init__(self, message: str) -> None:
        super().__init__("enforcement", message)


class StorageQuotaMismatchError(InfrastructureTrialError):
    def __init__(self, message: str) -> None:
        super().__init__("enforcement", message)


class NetworkPolicyMismatchError(InfrastructureTrialError):
    def __init__(self, message: str) -> None:
        super().__init__("enforcement", message)


class ReadOnlyMismatchError(InfrastructureTrialError):
    def __init__(self, message: str) -> None:
        super().__init__("enforcement", message)


class StorageExhaustedError(CandidateTrialError):
    def __init__(self, message: str) -> None:
        super().__init__("storage_exhausted", message)


class MemoryLimitExceededError(CandidateTrialError):
    def __init__(self, message: str) -> None:
        super().__init__("memory_limit", message)


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
        mounted = _mount_paths(package)
        self._image = image
        self._name = name
        self._request = request
        self._command = command
        self._openrouter_api_key = openrouter_api_key
        self._workdir = runs_root / name
        self._workspace = self._workdir / "workspace"
        self._submission = self._workdir / "submission"
        self._baseline = self._workdir / "baseline"
        self._working_copy = self._submission / "worktree"
        self._scratch = self._workdir / "scratch"
        self._quota_image = self._workdir / "scratch.ext4"
        self._quota_mounted = False
        self._network_name = f"{name}-lan"
        self._network_interface = f"ap{name[-12:]}"[:15]
        self._network_created = False
        self._firewall_installed: list[tuple[str, list[str]]] = []
        self._expected_workspace = {
            path: content.encode("utf-8") for path, content in mounted.items()
        }
        repository = {
            path[len(_WORKSPACE_PACKAGE_PREFIX) :]: content
            for path, content in package.items()
            if path.startswith(_WORKSPACE_PACKAGE_PREFIX)
        }
        self._expected_baseline = {
            path: content.encode("utf-8") for path, content in repository.items()
        }
        runs_root.mkdir(parents=True, exist_ok=True)
        try:
            for directory in (
                self._workspace, self._submission, self._baseline, self._working_copy
            ):
                directory.mkdir(parents=True, exist_ok=True)
            # /submission is writable by the container's uid 1000.
            self._submission.chmod(0o777)
            materialize_under(self._workspace, mounted)
            materialize_under(self._baseline, repository)
            materialize_under(self._working_copy, repository)
            for directory in self._working_copy.rglob("*"):
                directory.chmod(0o777 if directory.is_dir() else 0o666)
            self._working_copy.chmod(0o777)
        except Exception:
            shutil.rmtree(self._workdir, ignore_errors=True)
            raise
        self._cancel = threading.Event()
        self._started = False
        self._deadline: float | None = None

    def set_deadline(self, deadline: float) -> None:
        """Receive the absolute monotonic acceptance deadline before setup."""
        self._deadline = deadline

    def _run_bounded(self, args: list[str], ceiling: float) -> subprocess.CompletedProcess[str]:
        """Run a docker step under the lower of its own ceiling and the budget.

        A step killed because the acceptance budget ran out is a deadline
        breach, not an unexplained subprocess failure: re-check the budget
        so the caller sees ``TrialTimeoutError`` rather than the generic
        ``unexpected_exception`` that a bare ``TimeoutExpired`` becomes.
        """
        try:
            return _run(args, timeout=min(ceiling, self._remaining()))
        except subprocess.TimeoutExpired:
            self._remaining()
            raise

    def _inspect_bounded(self) -> ContainerObservation | None:
        """Inspect the container under the acceptance budget.

        ``effective_enforcement`` deliberately keeps the unbounded
        ``_inspect``: it also runs from teardown, which must complete
        after a deadline breach rather than be cut short by it.
        """
        try:
            return _inspect(self._name, timeout=min(_POLL_TIMEOUT_S, self._remaining()))
        except subprocess.TimeoutExpired:
            self._remaining()
            raise

    def _remaining(self) -> float:
        assert self._deadline is not None
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise TrialTimeoutError("trial exceeded its worker-acceptance deadline")
        return remaining

    def cancel(self) -> None:
        """Operator-initiated cancellation, observable by an in-flight ``run()``."""
        self._cancel.set()
        if self._started and not _force_remove(self._name):
            raise InfrastructureTrialError("enforcement", "container removal failed")

    def _check_cancel(self) -> None:
        if self._cancel.is_set():
            raise TrialCancelledError("operator cancelled the trial")

    def _prepare_quota(self, limits: TrialLimits) -> None:
        self._scratch.mkdir()
        self._quota_image.touch()
        os.truncate(self._quota_image, limits.storage_mb * 1024 * 1024)
        formatted = self._run_bounded(
            ["mkfs.ext4", "-F", "-q", str(self._quota_image)], _START_TIMEOUT_S
        )
        if formatted.returncode != 0:
            raise InfrastructureTrialError(
                "enforcement", f"host envelope setup failed: mkfs.ext4: {formatted.stderr.strip()}"
            )
        _checked_host(
            [
                "mount",
                "-t",
                "ext4",
                "-o",
                "loop,nosuid,nodev",
                str(self._quota_image),
                str(self._scratch),
            ]
        )
        self._quota_mounted = True
        _checked_host(["chmod", "0777", str(self._scratch)])

    def _prepare_network(self) -> None:
        if self._request.network_policy != "egress-lan-host-port":
            return
        host = self._request.egress_host
        port = self._request.egress_port
        assert host is not None and port is not None
        result = self._run_bounded(
            [
                "docker",
                "network",
                "create",
                "--driver",
                "bridge",
                "--opt",
                f"com.docker.network.bridge.name={self._network_interface}",
                "--label",
                f"assay.egress.host={host}",
                "--label",
                f"assay.egress.port={port}",
                self._network_name,
            ],
            _START_TIMEOUT_S,
        )
        if result.returncode != 0:
            raise InfrastructureTrialError(
                "enforcement", f"LAN network setup failed: {result.stderr.strip()}"
            )
        self._network_created = True
        # Insert a per-interface deny rule first, then the single TCP exception.
        # These rules cover traffic to the host (INPUT) and routed traffic
        # (FORWARD); an IPv4 literal avoids a DNS escape path.
        for chain in ("INPUT", "FORWARD"):
            for rule in (
                ["-j", "DROP"],
                ["-p", "tcp", "-d", host, "--dport", str(port), "-j", "ACCEPT"],
            ):
                _checked_host(["iptables", "-I", chain, "1", "-i", self._network_interface, *rule])
                self._firewall_installed.append((chain, rule))

    def _assert_enforcement(self, observation: ContainerObservation | None) -> None:
        if observation is None:
            raise MountKindMismatchError("docker inspect did not confirm the trial mount")
        if (
            observation.scratch_mount_kind != "bind"
            or observation.scratch_tmpfs
            or observation.scratch_source != str(self._scratch)
        ):
            raise MountKindMismatchError("/scratch is not the inspected quota-backed bind mount")
        if observation.storage_limit_mb != self._request.limits.storage_mb:
            raise StorageQuotaMismatchError(
                "inspected /scratch filesystem quota differs from storage_mb"
            )
        if not observation.read_only_root or observation.workspace_mount_read_only is not True:
            raise ReadOnlyMismatchError("inspected root or baseline mount is writable")
        expected = "network-none-no-egress-allowlist"
        if self._request.network_policy == "egress-lan-host-port":
            expected = (
                f"egress-lan-host-port:{self._request.egress_host}:{self._request.egress_port}"
            )
        if observation.network_policy_label != expected:
            raise NetworkPolicyMismatchError(
                "inspected Docker network differs from the declared posture"
            )

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
            self._network_name
            if self._request.network_policy == "egress-lan-host-port"
            else "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
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
        self._check_cancel()
        if self._deadline is None:
            self._deadline = time.monotonic() + self._request.limits.timeout_s
        self._remaining()
        self._check_cancel()
        self._prepare_quota(self._request.limits)
        self._remaining()
        self._check_cancel()
        self._prepare_network()
        self._remaining()
        self._check_cancel()
        start_result = self._run_bounded(
            self._docker_run_args(self._request.limits), _START_TIMEOUT_S
        )
        self._remaining()
        if start_result.returncode != 0:
            raise InfrastructureTrialError(
                "container_start", f"container failed to start: {start_result.stderr.strip()}"
            )
        self._started = True
        self._check_cancel()
        self._assert_enforcement(_usable_observation(self._inspect_bounded()))
        while True:
            self._remaining()
            if self._cancel.is_set():
                raise TrialCancelledError("operator cancelled the trial")
            inspect = self._run_bounded(
                ["docker", "inspect", "--format", "{{.State.Running}}", self._name],
                _POLL_TIMEOUT_S,
            )
            self._remaining()
            if inspect.returncode == 0 and inspect.stdout.strip() == "false":
                break
            time.sleep(_POLL_INTERVAL_S)
        exit_code = self._run_bounded(
            ["docker", "inspect", "--format", "{{.State.ExitCode}}", self._name],
            _POLL_TIMEOUT_S,
        )
        observation = _usable_observation(self._inspect_bounded())
        self._assert_enforcement(observation)
        assert observation is not None
        if observation.oom_killed:
            raise MemoryLimitExceededError("trial exceeded the memory cgroup ceiling")
        if exit_code.stdout.strip() != "0":
            logs = self._run_bounded(["docker", "logs", self._name], _POLL_TIMEOUT_S)
            if exit_code.stdout.strip() == "124" and Path(self._command[0]).name == "timeout":
                # Exit 124 is a deadline only when the launched command is
                # the timeout utility; an arbitrary program may also use 124.
                raise CandidateTrialError(
                    "candidate_test_timeout",
                    "candidate command timed out",
                    artifacts=self._retained_submission(),
                )
            if logs.returncode == 0 and "MemoryError" in logs.stdout + logs.stderr:
                raise MemoryLimitExceededError("trial reported memory allocation failure")
            # A full filesystem is only evidence of capacity, not evidence
            # that the trial attempted a write which failed with ENOSPC.
            if logs.returncode == 0 and any(
                "/scratch" in line and ("No space left on device" in line or "[Errno 28]" in line)
                for line in (logs.stdout + logs.stderr).splitlines()
            ):
                raise StorageExhaustedError("trial reported ENOSPC on /scratch")
        submission_file = self._submission / "output"
        if exit_code.stdout.strip() != "0":
            raise CandidateTrialError(
                "nonzero_exit",
                "trial container exited nonzero",
                artifacts=self._retained_submission(),
            )
        if submission_file.is_symlink():
            raise CandidateTrialError(
                "symlink_submission",
                "submission marker is a symlink",
                artifacts=self._retained_submission(),
            )
        if not submission_file.is_file():
            raise CandidateTrialError(
                "no_submission",
                "trial wrote no submission marker",
                artifacts=self._retained_submission(),
            )
        if regular_tree(self._workspace) != self._expected_workspace or (
            regular_tree(self._baseline) != self._expected_baseline
        ):
            raise CandidateTrialError(
                "tampering",
                "immutable arm baseline changed during trial",
                artifacts=self._retained_submission(),
            )
        patch = submission_patch(self._baseline, self._working_copy)
        # Read the submission mount before teardown removes it: these bytes
        # exist nowhere else, and the caller cannot go back for them.
        artifacts = collect_artifacts(
            self._submission,
            max_bytes=MAX_ARTIFACT_BYTES,
            max_aggregate_bytes=MAX_AGGREGATE_ARTIFACT_BYTES,
            max_entries=MAX_SUBMISSION_ENTRIES,
            aggregate_exempt_path=MANIFEST_PATH,
            excluded_roots=frozenset({"worktree"}),
        )
        if "candidate.patch" in artifacts or MANIFEST_PATH in artifacts:
            raise CandidateTrialError(
                "tampering", "candidate attempted to replace host evidence", artifacts=artifacts
            )
        for path in artifacts:
            if path not in {
                "output",
                "trajectory.json",
                "result.json",
                "configuration.json",
            }:
                raise CandidateTrialError(
                    "out_of_scope_edit", f"unexpected submission path: {path}", artifacts=artifacts
                )
        try:
            artifacts["output"].decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise CandidateTrialError(
                "binary_payload", "submission marker is not UTF-8", artifacts=artifacts
            ) from error
        if "configuration.json" in artifacts:
            raise CandidateTrialError(
                "tampering",
                "candidate attempted to supply resolved configuration",
                artifacts=artifacts,
            )
        if "trajectory.json" not in artifacts:
            logs = self._run_bounded(["docker", "logs", self._name], _POLL_TIMEOUT_S)
            artifacts["trajectory.json"] = canonical_json(
                {"container_stdout": logs.stdout, "container_stderr": logs.stderr}
            )
        artifacts.setdefault(
            "result.json",
            canonical_json({"exit_status": "Submitted", "container_exit_code": 0, "usage": None}),
        )
        artifacts["configuration.json"] = canonical_json(
            {
                "model_route": self._request.model_route.model_dump(mode="json"),
                "limits": self._request.limits.model_dump(mode="json"),
            }
        )
        artifacts["candidate.patch"] = patch.patch
        # The worker's own counts, if it reported any. This cell has no
        # pricing model, so the cost stays unobserved rather than zero.
        usage = worker_usage_from_result_bytes(artifacts["result.json"])
        artifacts = seal_observed_artifacts(
            self._request.exchange,
            artifacts,
            regular_tree(self._working_copy),
            patch.final_tree_digest,
        )
        (self._submission / MANIFEST_PATH).write_bytes(artifacts[MANIFEST_PATH])
        return TrialResult(
            cell_id=self._request.cell_id,
            outcome=CandidateSubmission(
                patch_ref=_digest(patch.patch),
                tree_digest=patch.final_tree_digest,
                baseline_tree_digest=patch.baseline_tree_digest,
            ),
            usage=usage,
            effective=self.effective_enforcement(),
            artifacts=artifacts,
        )

    def partial_artifacts(self) -> dict[str, bytes]:
        return collect_artifacts(
            self._submission,
            max_bytes=MAX_ARTIFACT_BYTES,
            max_aggregate_bytes=MAX_AGGREGATE_ARTIFACT_BYTES,
            max_entries=MAX_SUBMISSION_ENTRIES,
            aggregate_exempt_path=MANIFEST_PATH,
            excluded_roots=frozenset({"worktree"}),
        )

    def _retained_submission(self) -> dict[str, bytes]:
        try:
            return self.partial_artifacts()
        except ArtifactCollectionRejected as rejection:
            return rejection.artifacts
        except Exception:
            return {}

    def effective_enforcement(self) -> EffectiveEnforcement:
        try:
            observation = _usable_observation(_inspect(self._name))
        except Exception:
            observation = None
        try:
            count = _container_count(self._name)
        except Exception:
            count = None
        return self._effective_enforcement(observation, count)

    def _effective_enforcement(
        self, observation: ContainerObservation | None, count: int | None
    ) -> EffectiveEnforcement:
        containers_remaining = count if count is not None else 1
        return EffectiveEnforcement(
            uid=observation.uid if observation else 0,
            gid=observation.gid if observation else 0,
            workspace_read_only=bool(observation.workspace_mount_read_only)
            if observation and observation.workspace_mount_read_only is not None
            else False,
            root_read_only=observation.read_only_root if observation else False,
            submission_mount="/submission",
            scratch_mount="/scratch",
            scratch_mount_kind=observation.scratch_mount_kind if observation else "unknown",
            scratch_quota_mb=observation.storage_limit_mb if observation else 0,
            network_policy=observation.network_policy_label if observation else "unknown",
            cpu_limit=observation.cpu_limit if observation else 0,
            memory_limit_mb=observation.memory_limit_mb if observation else 0,
            pids_limit=observation.pids_limit if observation else 0,
            storage_limit_mb=observation.storage_limit_mb if observation else 0,
            containers_remaining=containers_remaining,
            child_processes_remaining=0,
            teardown_completed=(
                containers_remaining == 0
                and not self._firewall_installed
                and not self._network_created
                and not self._quota_mounted
                and not self._workdir.exists()
            ),
        )

    def teardown(self) -> EffectiveEnforcement:
        # Observe before destroying: once removed, docker inspect can no
        # longer report what the container actually enforced.
        try:
            observation = _usable_observation(_inspect(self._name))
        except Exception:
            observation = None
        with contextlib.suppress(Exception):
            _force_remove(self._name)
        failed_rules: list[tuple[str, list[str]]] = []
        for chain, rule in reversed(self._firewall_installed):
            try:
                removed = _host_run(["iptables", "-D", chain, "-i", self._network_interface, *rule])
            except Exception:
                failed_rules.append((chain, rule))
            else:
                if removed.returncode != 0:
                    failed_rules.append((chain, rule))
        self._firewall_installed = list(reversed(failed_rules))
        if self._network_created:
            try:
                removed = _run(
                    ["docker", "network", "rm", self._network_name], timeout=_REMOVE_TIMEOUT_S
                )
            except Exception:
                pass
            else:
                if removed.returncode == 0:
                    self._network_created = False
        if self._quota_mounted:
            try:
                unmounted = _host_run(["umount", str(self._scratch)])
            except Exception:
                pass
            else:
                if unmounted.returncode == 0:
                    self._quota_mounted = False
        if not self._quota_mounted:
            shutil.rmtree(self._workdir, ignore_errors=True)
        try:
            count = _container_count(self._name)
        except Exception:
            count = None
        return self._effective_enforcement(observation, count)


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
