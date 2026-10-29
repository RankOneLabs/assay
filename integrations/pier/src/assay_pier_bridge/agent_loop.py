"""One repository-capable agent attempt per cell.

The host owns the model connection. Only a fresh, network-disabled container
touches the cell's repository copy. No evaluator or hidden-test mount is passed
to that container. The workflow-edit tool set is read_file, write_file,
replace_in_file, run_command, and submit_output. The verification pilot adds
search_files and turn-specific submit_output schemas; results return to the
same cell's conversation.

The paid OpenRouter route is built in. Every other route is a ``TurnCompletion``
the caller injects, so the backend that drives turns is the one whose identity
the caller authorized (for the local fleet, Assay's pinned Smithers client).
"""

from __future__ import annotations

import io
import json
import math
import os
import re
import selectors
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from contextlib import suppress
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, NoReturn, Protocol

import httpx

from assay_pier_bridge.identity import canonical_json, digest_bytes
from assay_pier_bridge.paths import (
    ArtifactCollectionRejected,
    check_submission_scope,
    extract_workspace_archive,
    materialize_under,
    regular_tree,
    safe_relative_path,
    submission_patch,
)
from assay_pier_bridge.protocol import ModelRoute
from assay_pier_bridge.provider import (
    MAX_COMPLETION_PRICE_PER_MILLION,
    MAX_PROMPT_PRICE_PER_MILLION,
    MODEL,
    PROVIDER,
    PROVIDER_NAME,
)

SYSTEM_PROMPT = (
    "You are editing one repository copy in /workspace. Use read_file, write_file, "
    "replace_in_file, and run_command to inspect, edit, and check it. When the change "
    "is complete, call submit_output with a one-paragraph summary; your edits to the "
    "files are the submission. Only this cell's repository is available; hidden tests and "
    "reference answers are never available. Do not seek network access or install "
    "packages."
)
# A tool command may not outlive this, nor the cell's remaining budget.
MAX_TOOL_SECONDS = 120.0
# One model request's wall-clock bound, still capped by the cell deadline. A
# paid request that times out after dispatch has an unknown charge and halts
# the run (billing_uncertain), so this sits well above observed latency.
MODEL_REQUEST_SECONDS = 120.0
# The most model requests one cell may make. Twenty is the pilot's frozen
# bound; a free local route may raise it, since the cap there guards against
# runaway loops rather than spend.
MAX_MODEL_TURNS = 200
# A tmpfs with less than this free is treated as exhausted: a write that hit
# ENOSPC leaves a partial block, not exactly zero.
EXHAUSTED_FREE_KB = 1024


@dataclass(frozen=True, slots=True)
class LoopBounds:
    """Per-cell ceilings for the repository-agent loop (see config/workflow_edit.yaml)."""

    max_turns: int = 20
    max_tool_schema_bytes: int = 16_384
    max_tool_output_bytes: int = 32_768
    max_conversation_bytes: int = 81_920
    max_request_bytes: int = 98_304
    max_response_bytes: int = 131_072
    max_output_tokens: int = 8_192
    max_storage_mb: int = 512


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    """Docker ceilings for one agent container.

    In tmpfs mode every writable mount is RAM-backed and charged to the same
    memory cgroup, so memory must exceed the writable total or a full disk
    would surface as an OOM kill instead of ENOSPC.
    """

    memory_mb: int = 1_536
    pids: int = 128
    cpus: float = 1.0
    workspace_mb: int = 256
    cache_mb: int = 256
    tmp_mb: int = 256

    def __post_init__(self) -> None:
        writable = self.workspace_mb + self.cache_mb + self.tmp_mb
        if min(self.memory_mb, self.pids, self.workspace_mb, self.cache_mb, self.tmp_mb) < 1:
            raise ValueError("sandbox limits must be positive")
        if not math.isfinite(self.cpus) or self.cpus <= 0:
            raise ValueError("sandbox cpus must be positive")
        if self.memory_mb <= writable:
            raise ValueError("memory_mb must exceed the tmpfs writable total")

    @property
    def storage_mb(self) -> int:
        return self.workspace_mb + self.cache_mb


@dataclass(frozen=True, slots=True)
class ResolvedClientConfig:
    transport_retries: int
    attempts: int = 1
    concurrency: int = 1
    provider_retries: int = 0
    sdk_retries: int = 0


@dataclass(frozen=True, slots=True)
class ModelTurn:
    """One model response, normalized to the OpenAI chat shape the loop replays."""

    message: dict[str, Any]
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float | None
    observations: dict[str, Any] = field(default_factory=dict)
    started_at: str | None = None
    ended_at: str | None = None
    generation_id: str | None = None
    http_status: int | None = None
    error_body: str | None = None
    # No verified provider revision field exists in the response contract yet.
    model_revision: str = "unavailable"


class InFlightDeadline(ValueError):
    """The cell deadline expired while a model request was in flight."""

    def __init__(self, *, bytes_received: bool) -> None:
        super().__init__("agent_deadline")
        self.bytes_received = bytes_received


class ProviderResponseFailure(ValueError):
    """A non-success HTTP response whose bounded body is available for the request event."""

    def __init__(self, status: int, body: str, started_at: str, ended_at: str) -> None:
        super().__init__("provider_response")
        self.status = status
        self.body = body
        self.started_at = started_at
        self.ended_at = ended_at


@dataclass(frozen=True, slots=True)
class OpenRouterTurnRoute:
    """Pinned settings for one authorized repository-agent OpenRouter route."""

    endpoint: str
    model: str
    provider: str
    provider_name: str
    max_prompt_price_per_million: float
    max_completion_price_per_million: float
    # None delegates to LoopBounds for the repository-agent Haiku profile.
    # Explicit frontier limits are still enforced in addition to LoopBounds.
    max_request_body_bytes: int | None
    max_output_tokens: int | None
    tool_choice: Literal["auto", "forced"]


# The repository agent's Haiku limits come from LoopBounds. provider.py's
# 65,536-byte / 2,048-token limits govern its separate single-request client.
HAIKU_TURN_ROUTE = OpenRouterTurnRoute(
    endpoint="https://openrouter.ai/api/v1",
    model=MODEL,
    provider=PROVIDER,
    provider_name=PROVIDER_NAME,
    max_prompt_price_per_million=MAX_PROMPT_PRICE_PER_MILLION,
    max_completion_price_per_million=MAX_COMPLETION_PRICE_PER_MILLION,
    max_request_body_bytes=None,
    max_output_tokens=None,
    tool_choice="auto",
)


def _screening_route(
    model: str, provider: str, provider_name: str, prompt: float, completion: float
) -> OpenRouterTurnRoute:
    return OpenRouterTurnRoute(
        endpoint="https://openrouter.ai/api/v1", model=model, provider=provider,
        provider_name=provider_name, max_prompt_price_per_million=prompt,
        max_completion_price_per_million=completion, max_request_body_bytes=None,
        max_output_tokens=None, tool_choice="auto",
    )


# Verification-pilot screening routes, one pinned ZDR endpoint each. max_price
# is that endpoint's listed price on 2026-10-18, so a price rise refuses the
# request rather than billing more; the identities were probed the same day.
# Limits come from LoopBounds, as for Haiku.
PAID_TURN_ROUTES: dict[tuple[str, str], OpenRouterTurnRoute] = {
    (route.model, route.provider): route for route in (
        HAIKU_TURN_ROUTE,
        _screening_route("anthropic/claude-sonnet-5.5", "amazon-bedrock", "Amazon Bedrock",
                         2.0, 10.0),
        _screening_route("openai/gpt-6.1-sol", "azure/us", "Azure", 2.2, 11.0),
        # The same model on Azure's EU capacity, for when azure/us refuses large
        # requests at peak load. A separate route, since the endpoint is identity.
        _screening_route("openai/gpt-6.1-sol", "azure/eu", "Azure", 2.2, 11.0),
        _screening_route("google/gemini-4-argon", "google-vertex/global", "Google", 2.0, 10.0),
        _screening_route("qwen/qwen3.8-2.4t-a95b", "siliconflow/fp8", "SiliconFlow", 2.0, 6.0),
        _screening_route("deepseek/deepseek-v4-pro", "siliconflow/fp8", "SiliconFlow",
                         1.502, 3.135),
        _screening_route("moonshotai/kimi-k2.7-code", "moonshotai/int4", "Moonshot AI",
                         0.95, 4.0),
        # Self-trust small models. Haiku and Luna list a long-context tier (above
        # 100k and 272k prompt tokens); max_price pins that tier so a long cell is
        # billed at it rather than refused partway through.
        _screening_route("anthropic/claude-haiku-5.5", "amazon-bedrock", "Amazon Bedrock",
                         0.5, 2.5),
        _screening_route("openai/gpt-6-luna", "azure", "Azure", 0.2, 0.75),
        _screening_route("google/gemini-3.8-flash", "google-vertex/global", "Google",
                         0.75, 3.75),
        _screening_route("qwen/qwen3.8-27b", "deepinfra/bf16", "DeepInfra", 0.15, 1.875),
        _screening_route("openai/gpt-oss-20b", "deepinfra/bf16", "DeepInfra", 0.03, 0.14),
        _screening_route("mistralai/ministral-14b-2512", "mistral/zdr", "Mistral", 0.2, 0.2),
    )
}


class TurnCompletion(Protocol):
    """Produce exactly one model turn; never retry inference on the caller's behalf."""

    def __call__(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
        turn: int,
        deadline: float | None,
    ) -> ModelTurn: ...


class ModelDispatchError(RuntimeError):
    """A turn could not be produced. ``cause`` is a stable, named reason."""

    def __init__(self, cause: str, detail: str = "") -> None:
        self.cause = cause
        super().__init__(detail or cause)


@dataclass(frozen=True, slots=True)
class LoopResult:
    summary: str
    patch: bytes
    files: dict[str, bytes]
    baseline_tree_digest: str
    final_tree_digest: str
    trajectory: dict[str, Any]
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: float | None
    requests: int


class AgentLoopError(RuntimeError):
    """A trial ended at a named boundary; trajectory and observed work survive it."""

    def __init__(
        self,
        cause: str,
        trajectory: dict[str, Any],
        *,
        evidence: Mapping[str, bytes] | None = None,
        rejection: ArtifactCollectionRejected | None = None,
        usage: Mapping[str, int | float | None] | None = None,
    ) -> None:
        self.cause = cause
        self.trajectory = trajectory
        self.evidence = dict(evidence or {})
        self.rejection = rejection
        self.usage = dict(usage or {})
        super().__init__(cause)


class BilledResponseError(ValueError):
    """A successful HTTP response failed validation after billing was possible."""

    def __init__(
        self, cause: str, usage: Mapping[str, int | float | None],
        provenance: Mapping[str, Any] | None = None,
    ) -> None:
        self.usage = dict(usage)
        self.provenance = dict(provenance or {})
        super().__init__(cause)


def _read_billed_usage(data: Any) -> dict[str, int | float | None]:
    raw = data.get("usage") if isinstance(data, dict) else None
    usage = raw if isinstance(raw, dict) else {}
    cost = usage.get("cost")
    measured_cost = (
        float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool)
        and math.isfinite(cost) and cost >= 0 else None
    )
    counts = {
        key: value if type(value) is int and value >= 0 else None
        for key in ("prompt_tokens", "completion_tokens")
        for value in (usage.get(key),)
    }
    return {**counts, "cost_usd": measured_cost}


class ToolSandbox(Protocol):
    name: str

    def execute(
        self,
        argv: list[str],
        *,
        max_output_bytes: int,
        input_text: str | None = None,
        timeout_s: float = MAX_TOOL_SECONDS,
    ) -> ToolOutput: ...
    def capture_workspace(self) -> dict[str, int]: ...
    def oom_kills(self) -> int | None: ...
    def interrupt(self) -> None: ...
    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ToolOutput:
    text: str
    original_bytes: int
    truncated: bool
    read_range: tuple[int, int] | None = None
    page_truncated: bool = False


class CellStorage(Protocol):
    workspace: Path
    cache: Path
    mounted: bool

    def prepare(self) -> None: ...
    def close(self) -> None: ...


class QuotaCellStorage:
    """One private ext4 quota for both writable container mounts."""

    def __init__(self, cell_root: Path, max_storage_mb: int) -> None:
        self.mount = cell_root / "quota"
        self.image = cell_root / "quota.ext4"
        self.workspace = self.mount / "workspace"
        self.cache = self.mount / "cache"
        self.max_storage_mb = max_storage_mb
        self.mounted = False

    @staticmethod
    def _host_command(argv: list[str]) -> subprocess.CompletedProcess[str]:
        command = argv if os.geteuid() == 0 else ["sudo", "-n", *argv]
        return subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)

    def prepare(self) -> None:
        self.mount.mkdir(parents=True, exist_ok=False)
        self.image.touch(exist_ok=False)
        os.truncate(self.image, self.max_storage_mb * 1024 * 1024)
        formatted = subprocess.run(
            ["mkfs.ext4", "-F", "-q", str(self.image)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if formatted.returncode:
            raise ValueError("storage_format")
        mounted = self._host_command(
            ["mount", "-t", "ext4", "-o", "loop,nosuid,nodev", str(self.image), str(self.mount)]
        )
        if mounted.returncode:
            raise ValueError("storage_mount")
        self.mounted = True
        if not os.path.ismount(self.mount):
            raise ValueError("storage_quota_unverified")
        stats = os.statvfs(self.mount)
        if stats.f_blocks * stats.f_frsize > self.max_storage_mb * 1024 * 1024:
            raise ValueError("storage_quota_unverified")
        if self._host_command(["chmod", "0777", str(self.mount)]).returncode:
            raise ValueError("storage_permissions")
        self.workspace.mkdir()
        self.cache.mkdir()

    def close(self) -> None:
        if self.mounted:
            if self._host_command(["umount", str(self.mount)]).returncode:
                raise RuntimeError("storage_cleanup")
            self.mounted = False


class DockerTmpfsStagingStorage:
    """Host staging only; the paired Docker sandbox enforces the real quota."""

    def __init__(self, cell_root: Path, max_storage_mb: int) -> None:
        self.workspace = cell_root / "staging" / "workspace"
        self.cache = cell_root / "staging" / "cache"
        self.max_storage_mb = max_storage_mb
        self.mounted = False

    def prepare(self) -> None:
        self.workspace.mkdir(parents=True)
        self.cache.mkdir()

    def close(self) -> None:
        pass


class ContainerStartError(RuntimeError):
    def __init__(self, returncode: int, *, cleanup_failed: bool) -> None:
        self.cleanup_failed = cleanup_failed
        super().__init__(f"container_start:{returncode}")


_OBSERVE = (
    "cat /sys/fs/cgroup/memory.peak /sys/fs/cgroup/pids.peak && "
    "grep '^oom_kill ' /sys/fs/cgroup/memory.events | cut -d' ' -f2 && "
    "df -Pk /workspace /cache | tail -n 2 | tr -s ' ' | cut -d' ' -f4"
)


_OOM_KILLS = "grep '^oom_kill ' /sys/fs/cgroup/memory.events | cut -d' ' -f2"


_KILL_STRAYS = (
    "for entry in /proc/[0-9]*; do pid=${entry#/proc/}; "
    'if [ "$pid" != 1 ] && [ "$pid" != $$ ]; then kill -9 "$pid" 2>/dev/null; fi; done; true'
)


class DockerToolSandbox:
    """Disposable container with only the neutral repository and cache mounts."""

    def __init__(
        self,
        workspace: Path,
        cache: Path,
        image: str,
        cell_id: str,
        *,
        tmpfs_storage: bool = False,
        limits: SandboxLimits | None = None,
        index_mount: str | None = None,
        index_files: Mapping[str, bytes] | None = None,
        index_agent_readable: bool = True,
    ) -> None:
        limits = limits or SandboxLimits()
        self.name = f"assay-agent-{uuid.uuid4().hex}"
        self._closed = False
        self._close_lock = threading.Lock()
        self._workspace = workspace
        self._tmpfs_storage = tmpfs_storage
        if (index_mount is None) != (index_files is None):
            raise ValueError("codeintel_index_failure")
        if index_mount is not None and (
            not index_mount.startswith("/") or index_mount == "/workspace"
            or index_mount.startswith("/workspace/")
        ):
            raise ValueError("codeintel_index_failure")
        index_host: Path | None = None
        if index_mount is not None and not tmpfs_storage:
            index_host = (cache / index_mount.removeprefix("/cache/")) if (
                index_mount.startswith("/cache/")
            ) else (cache if index_mount == "/cache" else cache.parent / "codeintel-index")
            try:
                index_host.mkdir(parents=True, exist_ok=True)
                for filename, content in (index_files or {}).items():
                    if filename != "index.json":
                        raise ValueError("unsupported index file")
                    target = index_host / filename
                    target.write_bytes(content)
                    target.chmod(0o644 if index_agent_readable else 0o000)
            except (OSError, ValueError) as error:
                raise ValueError("codeintel_index_failure") from error
        mounts = (
            [
                "--tmpfs", f"/workspace:size={limits.workspace_mb}m,mode=1777",
                "--tmpfs", f"/cache:size={limits.cache_mb}m,mode=1777",
            ]
            if tmpfs_storage
            else ["-v", f"{workspace}:/workspace:rw", "-v", f"{cache}:/cache:rw"]
        )
        if index_mount is not None and not (
            index_mount == "/cache" or index_mount.startswith("/cache/")
        ):
            if tmpfs_storage:
                mounts.extend(["--tmpfs", f"{index_mount}:size={limits.cache_mb}m,mode=1777"])
            else:
                assert index_host is not None
                mounts.extend(["-v", f"{index_host}:{index_mount}:rw"])
        command = [
            "docker",
            "run",
            "-d",
            "--name",
            self.name,
            "--label",
            f"assay-cell={cell_id}",
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            f"/tmp:size={limits.tmp_mb}m",
            "--env",
            "HOME=/cache",
            "--env",
            "XDG_CACHE_HOME=/cache",
            "--env",
            "NPM_CONFIG_CACHE=/cache/npm",
            "--env",
            "BUN_INSTALL_CACHE_DIR=/cache/bun",
            "--user",
            "1000:1000",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(limits.pids),
            "--memory",
            f"{limits.memory_mb}m",
            "--cpus",
            str(limits.cpus),
            *mounts,
            "--workdir",
            "/workspace",
            "--entrypoint",
            "sleep",
            image,
            "infinity",
        ]
        try:
            started = subprocess.run(
                command, capture_output=True, text=True, timeout=30, check=False
            )
        except (OSError, subprocess.SubprocessError) as error:
            self._failed_start(-1, cause=error)
        if started.returncode:
            self._failed_start(started.returncode)
        if tmpfs_storage:
            try:
                archive = io.BytesIO()
                with tarfile.open(fileobj=archive, mode="w") as stream:
                    for path in sorted(workspace.rglob("*")):
                        stream.add(path, arcname=path.relative_to(workspace), recursive=False)
                copied = subprocess.run(
                    ["docker", "exec", "-i", self.name, "tar", "-x", "-C", "/workspace"],
                    input=archive.getvalue(), capture_output=True, timeout=30, check=False,
                )
            except Exception as error:
                self._failed_start(-1, cause=error)
            if copied.returncode:
                self._failed_start(copied.returncode)
            if index_mount is not None:
                try:
                    archive = io.BytesIO()
                    with tarfile.open(fileobj=archive, mode="w") as stream:
                        for filename, content in (index_files or {}).items():
                            if filename != "index.json":
                                raise ValueError("unsupported index file")
                            member = tarfile.TarInfo(filename)
                            member.size = len(content)
                            member.mode = 0o644 if index_agent_readable else 0o000
                            stream.addfile(member, io.BytesIO(content))
                    made = subprocess.run(
                        ["docker", "exec", self.name, "mkdir", "-p", index_mount],
                        capture_output=True, timeout=30, check=False,
                    )
                    if made.returncode:
                        raise RuntimeError("index mount directory")
                    copied = subprocess.run(
                        ["docker", "exec", "-i", self.name, "tar", "-x", "-C", index_mount],
                        input=archive.getvalue(), capture_output=True, timeout=30, check=False,
                    )
                    if copied.returncode:
                        raise RuntimeError("index tar stream")
                except Exception as error:
                    with suppress(OSError, RuntimeError, subprocess.SubprocessError):
                        self.close()
                    raise ValueError("codeintel_index_failure") from error
        self.observed = self._inspect()

    def _inspect(self) -> dict[str, Any]:
        """What Docker actually applied, not what this class asked for."""
        try:
            inspected = subprocess.run(
                ["docker", "inspect", "--format", "{{json .HostConfig}}|{{json .Config.User}}",
                 self.name],
                capture_output=True, text=True, timeout=30, check=False,
            )
            host_raw, user_raw = inspected.stdout.strip().split("|", 1)
            host = json.loads(host_raw)
            user = json.loads(user_raw)
        except Exception as error:
            self._failed_start(-1, cause=error)
        if inspected.returncode or not isinstance(host, dict):
            self._failed_start(inspected.returncode or -1)
        tmpfs = host.get("Tmpfs") if isinstance(host.get("Tmpfs"), dict) else {}
        return {
            "user": user,
            "network_mode": host.get("NetworkMode"),
            "readonly_rootfs": host.get("ReadonlyRootfs"),
            "memory_bytes": host.get("Memory"),
            "pids_limit": host.get("PidsLimit"),
            "nano_cpus": host.get("NanoCpus"),
            "cap_drop": host.get("CapDrop"),
            "tmpfs": tmpfs,
        }

    def capture_workspace(self) -> dict[str, int]:
        """Read the cgroup and filesystem observations, then copy the tree out.

        Only the tmpfs mode needs a copy: a bind mount is already the host tree.
        """
        if not self._tmpfs_storage:
            return {}
        observed = self.execute(["/bin/sh", "-c", _OBSERVE], max_output_bytes=1024)
        values = observed.text.splitlines()
        if len(values) != 6 or values[0] != "exit=0":
            raise RuntimeError("cgroup_peak_observation")
        try:
            memory_peak, pids_peak, oom_kills, workspace_free, cache_free = map(int, values[1:])
        except ValueError as error:
            raise RuntimeError("cgroup_peak_observation") from error
        # ``docker cp`` reads the container's layered filesystem and silently
        # returns nothing from a tmpfs mount, so the tree is streamed out.
        archived = subprocess.run(
            [
                "docker", "exec", "-u", "0:0", self.name, "tar", "-c", "-f", "-",
                "-C", "/workspace", ".",
            ],
            capture_output=True, timeout=60, check=False,
        )
        if archived.returncode:
            if b"permission denied" in archived.stderr.lower():
                raise ArtifactCollectionRejected(
                    "workspace_capture_permission", "cannot read candidate workspace",
                    origin="working_copy",
                )
            raise RuntimeError("workspace_capture")
        for path in self._workspace.iterdir():
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
        extract_workspace_archive(archived.stdout, self._workspace)
        return {
            "memory_peak_bytes": memory_peak,
            "pids_peak": pids_peak,
            "oom_kills": oom_kills,
            "workspace_free_kb": workspace_free,
            "cache_free_kb": cache_free,
        }

    def oom_kills(self) -> int | None:
        """The cell cgroup's cumulative OOM-kill count, read after each tool call.

        ``None`` in bind-mount mode, which, like ``capture_workspace``, observes
        no cgroup counters.
        """
        if not self._tmpfs_storage:
            return None
        observed = self.execute(["/bin/sh", "-c", _OOM_KILLS], max_output_bytes=256, timeout_s=30)
        values = observed.text.splitlines()
        if len(values) != 2 or values[0] != "exit=0":
            raise RuntimeError("cgroup_peak_observation")
        try:
            return int(values[1])
        except ValueError as error:
            raise RuntimeError("cgroup_peak_observation") from error

    def _failed_start(self, returncode: int, *, cause: Exception | None = None) -> NoReturn:
        cleanup_failed = False
        try:
            self.close()
        except (RuntimeError, OSError, subprocess.SubprocessError):
            cleanup_failed = True
        raise ContainerStartError(returncode, cleanup_failed=cleanup_failed) from cause

    def execute(
        self,
        argv: list[str],
        *,
        max_output_bytes: int,
        input_text: str | None = None,
        timeout_s: float = MAX_TOOL_SECONDS,
    ) -> ToolOutput:
        command = ["docker", "exec", "-i", "-w", "/workspace", self.name, *argv]
        with tempfile.TemporaryFile() as input_file:
            if input_text is not None:
                input_file.write(input_text.encode("utf-8"))
                input_file.seek(0)
            process = subprocess.Popen(
                command,
                stdin=input_file if input_text is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            assert process.stdout is not None
            deadline = time.monotonic() + max(timeout_s, 0.0)
            captured = bytearray()
            original_bytes = 0
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0 or not selector.select(remaining):
                            raise RuntimeError("tool_timeout")
                        chunk = os.read(process.stdout.fileno(), 8192)
                        if not chunk:
                            break
                        original_bytes += len(chunk)
                        if len(captured) < max_output_bytes:
                            captured.extend(chunk[: max_output_bytes - len(captured)])
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("tool_timeout")
                returncode = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired as error:
                raise RuntimeError("tool_timeout") from error
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
                process.stdout.close()
        prefix = f"exit={returncode}\n".encode()
        bounded = (prefix + captured)[:max_output_bytes]
        total_bytes = len(prefix) + original_bytes
        return ToolOutput(
            bounded.decode("utf-8", errors="ignore"),
            total_bytes,
            total_bytes > max_output_bytes,
        )

    def interrupt(self) -> None:
        """Kill everything but the container's own PID 1 after a tool timed out.

        Killing the ``docker exec`` client leaves its process running inside
        the container, still holding the cell's one CPU.
        """
        killed = subprocess.run(
            ["docker", "exec", self.name, "/bin/sh", "-c", _KILL_STRAYS],
            capture_output=True, text=True, timeout=30, check=False,
        )
        if killed.returncode:
            raise RuntimeError("tool_interrupt")

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            removed = subprocess.run(
                ["docker", "rm", "-f", self.name],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if removed.returncode:
                raise RuntimeError("container_cleanup")
            self._closed = True


class DockerTmpfsToolSandbox(DockerToolSandbox):
    """The declared local sandbox: Docker-enforced tmpfs quotas, no host privileges."""

    def __init__(
        self, workspace: Path, cache: Path, image: str, cell_id: str,
        *, limits: SandboxLimits | None = None,
        index_mount: str | None = None,
        index_files: Mapping[str, bytes] | None = None,
        index_agent_readable: bool = True,
    ) -> None:
        super().__init__(
            workspace, cache, image, cell_id, tmpfs_storage=True, limits=limits,
            index_mount=index_mount, index_files=index_files,
            index_agent_readable=index_agent_readable,
        )


SandboxFactory = Callable[[Path, Path, str, str], ToolSandbox]


def _tool(name: str, description: str, properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": list(properties),
                "properties": properties,
            },
            "strict": True,
        },
    }


# Order is part of the authorized tool identity (``tools_sha256``); never reorder.
TOOLS = [
    _tool(
        "read_file",
        "Read a repository file by relative path. start_line and end_line (1-based, "
        "inclusive; null for the file's first or last line) select a range of lines. "
        "Output over the tool output limit ends at a whole line with a note giving the "
        "next start_line.",
        {
            "path": {"type": "string"},
            "start_line": {"type": ["integer", "null"]},
            "end_line": {"type": ["integer", "null"]},
        },
    ),
    _tool(
        "write_file",
        "Write a repository file by relative path, replacing its whole content.",
        {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
    ),
    _tool(
        "replace_in_file",
        "Replace the one exact occurrence of old with new in a repository file. Fails, "
        "changing nothing, unless old occurs exactly once; include surrounding lines to "
        "make it unique.",
        {
            "path": {"type": "string"},
            "old": {"type": "string"},
            "new": {"type": "string"},
        },
    ),
    _tool(
        "run_command",
        "Run a shell command inside the isolated repository container.",
        {
            "command": {"type": "string"},
        },
    ),
    _tool(
        "submit_output",
        "Finish this attempt. The repository files as they now stand are the submission.",
        {
            "summary": {"type": "string"},
        },
    ),
]

# The verification pilot has a separate, explicitly versioned tool surface.
# Keeping TOOLS intact preserves the workflow-edit study's pinned identity.
_SEARCH_FILES_TOOL = _tool(
    "search_files",
    "Search UTF-8 repository text for a literal query within an explicit relative "
    "file or directory scope. Use '.' for the whole repository.",
    {"scope": {"type": "string"}, "query": {"type": "string"}},
)
_T1_SUBMIT_TOOL = _tool(
    "submit_output", "End T1 and submit the proposed change title and body.",
    {"title": {"type": "string"}, "body": {"type": "string"}},
)
_REVIEW_SUBMIT_TOOL = _tool(
    "submit_output", "End this review turn with a verdict and evidence.",
    {
        "verdict": {"type": "string", "enum": ["complete", "incomplete", "unsure"]},
        "remaining_v1": {"type": "string"},
        "checks_performed": {"type": "string"},
    },
)
PILOT_TOOLS_T1 = [*deepcopy(TOOLS[:-1]), _SEARCH_FILES_TOOL, _T1_SUBMIT_TOOL]
PILOT_TOOLS_REVIEW = [*deepcopy(TOOLS[:-1]), _SEARCH_FILES_TOOL, _REVIEW_SUBMIT_TOOL]
PILOT_TOOL_SCHEMAS = {"T1": PILOT_TOOLS_T1, "T2_T3": PILOT_TOOLS_REVIEW}

# Extension trials have their own pinned surface.  The three nullable fields
# preserve an explicit "no self-assessment" submission under strict tool schemas.
_EXTENSION_SUBMIT_TOOL = _tool(
    "submit_output",
    "Finish this extension attempt and report your assessment of the submitted files.",
    {
        "summary": {"type": "string"},
        "self_assessed_verdict": {
            "type": ["string", "null"],
            "enum": ["complete", "incomplete", "unsure", None],
        },
        "checks_performed": {"type": ["string", "null"]},
        "remaining_work": {"type": ["string", "null"]},
    },
)
EXTENSION_TOOLS = [*deepcopy(TOOLS[:-1]), _EXTENSION_SUBMIT_TOOL]
_FORBIDDEN_REPOSITORY_PARTS = frozenset({"hidden_tests", "hidden-tests", "reference_solutions"})
# Causes that end a cell because of what the model did, not the harness.
CANDIDATE_STOP_CAUSES = frozenset(
    {
        "turn_limit",
        "no_tool_call",
        "empty_reply",
        "invalid_tool_call",
        "invalid_submission",
        "output_token_limit",
        "conversation_limit",
        "request_limit",
        "turn_tool_call_limit",
        "cell_tool_call_limit",
    }
)


def _json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError as error:
        raise ArtifactCollectionRejected(
            "invalid_tool_output_encoding", "tool output is not UTF-8 encodable",
            origin="working_copy",
        ) from error


def _bounded_text(text: str, limit: int) -> tuple[str, bool]:
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ArtifactCollectionRejected(
            "invalid_tool_output_encoding", "tool output is not UTF-8 encodable",
            origin="working_copy",
        ) from error
    if len(encoded) <= limit:
        return text, False
    return encoded[:limit].decode("utf-8", errors="ignore"), True


def _submission(
    arguments: dict[str, Any], logical_turn: int, pilot_mode: bool,
    extension_mode: bool = False,
) -> dict[str, Any]:
    """Validate exactly the schema advertised for this turn."""
    if extension_mode:
        fields = {"summary", "self_assessed_verdict", "checks_performed", "remaining_work"}
        if set(arguments) != fields or not isinstance(arguments["summary"], str):
            raise ToolArgumentError(
                "extension submit_output requires summary and assessment fields"
            )
        if arguments["self_assessed_verdict"] not in {"complete", "incomplete", "unsure", None}:
            raise ToolArgumentError("invalid self-assessed verdict")
        if any(arguments[key] is not None and not isinstance(arguments[key], str)
               for key in ("checks_performed", "remaining_work")):
            raise ToolArgumentError("assessment details must be strings or null")
        if arguments["self_assessed_verdict"] is None and any(
            arguments[key] is not None for key in ("checks_performed", "remaining_work")
        ):
            raise ToolArgumentError("assessment details require a verdict")
        return arguments
    if not pilot_mode:
        if set(arguments) == {"summary"} and isinstance(arguments["summary"], str):
            return {"summary": arguments["summary"]}
        raise ToolArgumentError("submit_output takes only a summary")
    fields = {"title", "body"} if logical_turn == 1 else {
        "verdict", "remaining_v1", "checks_performed"
    }
    if set(arguments) != fields or any(not isinstance(value, str) for value in arguments.values()):
        raise ToolArgumentError(f"submit_output requires {', '.join(sorted(fields))}")
    if logical_turn > 1 and arguments["verdict"] not in {"complete", "incomplete", "unsure"}:
        raise ToolArgumentError("verdict must be complete, incomplete, or unsure")
    return arguments


def _read_coverage(
    arguments: dict[str, Any], output: ToolOutput, host_truncated: bool
) -> dict[str, Any]:
    """Only count source lines whose complete bytes reached the model."""
    if not output.text.startswith("exit=0\n"):
        return {}
    start = arguments.get("start_line") or 1
    end = (
        output.read_range[1]
        if output.read_range is not None and not host_truncated else start - 1
    )
    return {"path": arguments["path"], "start_line": start,
            "end_line": end, "complete": not (host_truncated or output.page_truncated)}


def _prepare_container_writes(workspace: Path, cache: Path) -> None:
    """Permit container UID 1000 to edit this cell's private mounted tree."""
    for directory in (workspace, cache):
        directory.chmod(0o777)
    for path in workspace.rglob("*"):
        path.chmod(0o777 if path.is_dir() else 0o666)


class ToolArgumentError(ValueError):
    """The model's call cannot run as written; the reason goes back to the model."""


def _relative_path(arguments: dict[str, Any]) -> str:
    path = arguments.get("path")
    if not isinstance(path, str):
        raise ToolArgumentError("path must be a string")
    try:
        return safe_relative_path(path).as_posix()
    except ValueError as error:
        raise ToolArgumentError(str(error)) from error


def _line_number(arguments: dict[str, Any], key: str) -> int | None:
    value = arguments.get(key)
    if value is None:
        return None
    if type(value) is not int or value < 1:
        raise ToolArgumentError(f"{key} must be a positive integer or null")
    return value


# Exit status of a tool script that refuses the call as written. The loop
# returns the script's one-line reason to the model as a tool error.
TOOL_REFUSED_EXIT = 3
# Room a paged read keeps for its truncation note inside the output cap.
_READ_NOTE_BYTES = 256
# Internal read metadata is stripped before the model sees the tool result.
_READ_META_BYTES = 256

# Runs in the container. Lines split on "\n" only, so a line number means the
# same thing to the model, to ``replace_in_file``, and to an editor. A page
# ends at a whole line and says where the next one starts.
_READ_FILE = """
import sys
from pathlib import Path

def refuse(reason):
    sys.stdout.buffer.write(reason.encode('utf-8'))
    raise SystemExit(@REFUSED@)

relative = sys.argv[1]
start, end, budget = (int(value) for value in sys.argv[2:5])
try:
    data = (Path('/workspace') / relative).read_bytes()
except OSError as error:
    refuse(f'{error.strerror or error}: {relative}')
parts = data.decode('utf-8', errors='replace').split('\\n')
lines = [part + '\\n' for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])
total = len(lines)
if start > max(total, 1):
    refuse(f'start_line {start} is past the end of {relative} ({total} lines)')
last = total if end == 0 else min(end, total)
room = max(budget - @NOTE@, 1)
shown, used = [], 0
for line in lines[start - 1:last]:
    size = len(line.encode('utf-8'))
    if used + size > room:
        break
    shown.append(line)
    used += size
following = start + len(shown)
out = ''.join(shown)
if following <= last and shown:
    out += (
        f'[truncated at the tool output limit: showed lines {start}-{following - 1} of '
        f'{total}; {last - following + 1} lines of the requested range remain; '
        f'continue with start_line={following}]'
    )
elif following <= last:
    head = lines[start - 1].encode('utf-8')[:room].decode('utf-8', errors='ignore')
    rest = (
        f'{last - start} lines of the requested range remain; continue with '
        f'start_line={start + 1}' if last > start else 'no lines of the requested range remain'
    )
    out = head + (
        f'\\n[truncated: line {start} alone exceeds the tool output limit and only its first '
        f'{len(head.encode("utf-8"))} bytes are shown; {rest}]'
    )
sys.stdout.buffer.write(
    f'@assay-read:{start}:{following - 1}:{int(following <= last)}\\n'.encode('ascii')
)
sys.stdout.buffer.write(out.encode('utf-8'))
""".replace("@REFUSED@", str(TOOL_REFUSED_EXIT)).replace("@NOTE@", str(_READ_NOTE_BYTES))

# Runs in the container. The same path rule as write_file: the target must
# resolve inside /workspace. Bytes are read and written untranslated.
_REPLACE_IN_FILE = """
import json
import sys
from pathlib import Path

def refuse(reason):
    sys.stdout.buffer.write(reason.encode('utf-8'))
    raise SystemExit(@REFUSED@)

relative = sys.argv[1]
edit = json.loads(sys.stdin.buffer.read())
target = Path('/workspace') / relative
try:
    if not target.resolve().is_relative_to(Path('/workspace').resolve()):
        refuse(f'path resolves outside /workspace: {relative}')
    text = target.read_bytes().decode('utf-8')
except OSError as error:
    refuse(f'{error.strerror or error}: {relative}')
except UnicodeDecodeError:
    refuse(f'{relative} is not UTF-8 text')
count = text.count(edit['old'])
if count != 1:
    refuse(
        f'old occurs {count} times in {relative}; it must occur exactly once, '
        'so nothing was changed'
    )
target.write_bytes(text.replace(edit['old'], edit['new'], 1).encode('utf-8'))
sys.stdout.buffer.write(f'replaced 1 occurrence in {relative}'.encode('utf-8'))
""".replace("@REFUSED@", str(TOOL_REFUSED_EXIT))

_SEARCH_FILES = """
import os
import sys
from pathlib import Path

root = Path('/workspace').resolve()
scope, query = sys.argv[1:3]
target = root if scope == '.' else root / scope
if not target.resolve().is_relative_to(root):
    sys.stdout.write('scope resolves outside /workspace')
    raise SystemExit(@REFUSED@)
if not target.exists():
    sys.stdout.write(f'scope does not exist: {scope}')
    raise SystemExit(@REFUSED@)
def scoped_paths():
    if target.is_file():
        yield target
        return
    for directory_name, dirs, files in os.walk(target, followlinks=False):
        dirs[:] = sorted(dirs)
        directory = Path(directory_name)
        for name in sorted(files):
            yield directory / name

paths = scoped_paths()
for path in paths:
    if path.is_symlink() or not path.is_file():
        continue
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeDecodeError):
        continue
    relative = path.relative_to(root).as_posix()
    for number, line in enumerate(lines, 1):
        if query in line:
            sys.stdout.write(f'{relative}:{number}:{line}\\n')
""".replace("@REFUSED@", str(TOOL_REFUSED_EXIT))


def _execute_tool(
    sandbox: ToolSandbox,
    name: str,
    arguments: dict[str, Any],
    max_output_bytes: int,
    timeout_s: float,
    *,
    codeintel_query_script: str | None = None,
    codeintel_index_mount: str | None = None,
    codeintel_max_context_tokens: int = 0,
) -> ToolOutput:
    if name == "codeintel_query" and set(arguments) == {"kind", "text"}:
        kind, query = arguments["kind"], arguments["text"]
        if kind not in ("symbol", "references") or not isinstance(query, str) or not query:
            raise ToolArgumentError("query needs a supported kind and non-empty text")
        if (not codeintel_query_script or not codeintel_index_mount or
                codeintel_max_context_tokens < 1):
            raise ToolArgumentError("code-intelligence query is not configured")
        return sandbox.execute(
            ["python", "-c", codeintel_query_script,
             f"{codeintel_index_mount}/index.json", kind, query,
             str(min(codeintel_max_context_tokens, max(1, (max_output_bytes - 64) // 4)))],
            max_output_bytes=max_output_bytes, timeout_s=timeout_s,
        )
    if name == "search_files" and set(arguments) == {"scope", "query"}:
        scope, query = arguments["scope"], arguments["query"]
        if not isinstance(scope, str) or not isinstance(query, str) or not query:
            raise ToolArgumentError("scope and non-empty query must be strings")
        if scope != ".":
            try:
                scope = safe_relative_path(scope).as_posix()
            except ValueError as error:
                raise ToolArgumentError(str(error)) from error
        return sandbox.execute(
            ["python", "-c", _SEARCH_FILES, scope, query],
            max_output_bytes=max_output_bytes, timeout_s=timeout_s,
        )
    if name == "read_file" and set(arguments) <= {"path", "start_line", "end_line"}:
        start = _line_number(arguments, "start_line") or 1
        end = _line_number(arguments, "end_line")
        if end is not None and end < start:
            raise ToolArgumentError("end_line must not be before start_line")
        # The script's page budget leaves room for the sandbox's exit prefix.
        budget = max_output_bytes - len(f"exit={TOOL_REFUSED_EXIT}\n")
        output = sandbox.execute(
            ["python", "-c", _READ_FILE, _relative_path(arguments), str(start), str(end or 0),
             str(budget)],
            max_output_bytes=max_output_bytes + _READ_META_BYTES,
            timeout_s=timeout_s,
        )
        if not output.text.startswith("exit=0\n"):
            return output
        header, separator, body = output.text.removeprefix("exit=0\n").partition("\n")
        match = re.fullmatch(r"@assay-read:(\d+):(\d+):([01])", header)
        if not separator or match is None:
            raise RuntimeError("read_metadata")
        return ToolOutput(
            f"exit=0\n{body}",
            output.original_bytes - len(header.encode("ascii")) - 1,
            output.truncated,
            read_range=(int(match.group(1)), int(match.group(2))),
            page_truncated=match.group(3) == "1",
        )
    if name == "replace_in_file" and set(arguments) == {"path", "old", "new"}:
        old, new = arguments["old"], arguments["new"]
        if not isinstance(old, str) or not old:
            raise ToolArgumentError("old must be a non-empty string")
        if not isinstance(new, str):
            raise ToolArgumentError("new must be a string")
        return sandbox.execute(
            ["python", "-c", _REPLACE_IN_FILE, _relative_path(arguments)],
            max_output_bytes=max_output_bytes,
            input_text=json.dumps({"old": old, "new": new}),
            timeout_s=timeout_s,
        )
    if name == "write_file" and set(arguments) == {"path", "content"}:
        content = arguments["content"]
        if not isinstance(content, str):
            raise ToolArgumentError("content must be a string")
        script = (
            "from pathlib import Path; import sys; "
            "p=Path('/workspace')/sys.argv[1]; p.parent.mkdir(parents=True, exist_ok=True); "
            "assert p.resolve().is_relative_to(Path('/workspace').resolve()); "
            "p.write_text(sys.stdin.read(), encoding='utf-8')"
        )
        return sandbox.execute(
            ["python", "-c", script, _relative_path(arguments)],
            max_output_bytes=max_output_bytes,
            input_text=content,
            timeout_s=timeout_s,
        )
    if name == "run_command" and set(arguments) == {"command"}:
        command = arguments["command"]
        if not isinstance(command, str) or len(command.encode("utf-8")) > 8_192:
            raise ToolArgumentError("command must be a string of at most 8192 bytes")
        return sandbox.execute(
            ["sh", "-lc", command], max_output_bytes=max_output_bytes, timeout_s=timeout_s
        )
    raise ToolArgumentError(f"unknown tool or argument fields for {name!r}")


# Tools whose in-container script may refuse a call with ``TOOL_REFUSED_EXIT``.
_SCRIPTED_TOOLS = frozenset({"read_file", "replace_in_file", "search_files"})


class ConversationLimitError(ValueError):
    """The pinned conversation cannot fit within the candidate's byte ceiling."""

    cause = "conversation_limit"

    def __init__(self) -> None:
        super().__init__(self.cause)


def _shrink_conversation(
    messages: list[dict[str, Any]], limit: int, events: list[dict[str, Any]],
    prefix_length: int = 2,
) -> None:
    """Remove oldest completed tool exchanges after the pinned prefix."""
    if prefix_length < 0 or prefix_length > len(messages):
        raise ValueError("invalid conversation prefix length")
    while len(_json_bytes(messages)) > limit:
        if len(messages) <= prefix_length:
            raise ConversationLimitError
        # A completed exchange is an assistant tool-call message plus its tool results.
        if messages[prefix_length].get("role") != "assistant":
            raise ConversationLimitError
        removed = 1
        while (prefix_length + removed < len(messages)
               and messages[prefix_length + removed].get("role") == "tool"):
            removed += 1
        if prefix_length + removed == len(messages):
            raise ConversationLimitError  # Keep the latest exchange available to the model.
        del messages[prefix_length : prefix_length + removed]
        events.append({"kind": "conversation_truncated", "messages_removed": removed})


def _replayable_call(call: object) -> dict[str, Any]:
    """Exactly the OpenAI tool-call fields, with arguments as a JSON string.

    Backends add their own keys (an ``index``, native-dict arguments); the
    replayed turn carries only what every backend accepts back.
    """
    if not isinstance(call, dict):
        raise ValueError("invalid_tool_call")
    call_id, function = call.get("id"), call.get("function")
    if not isinstance(call_id, str) or not call_id or not isinstance(function, dict):
        raise ValueError("invalid_tool_call")
    name, raw = function.get("name"), function.get("arguments")
    if not isinstance(name, str):
        raise ValueError("invalid_tool_call")
    arguments = raw if isinstance(raw, str) else json.dumps(raw if raw is not None else {})
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


def _resource_cause(peaks: Mapping[str, int], oom_kills_seen: int) -> str | None:
    """The resource cause the final submission check finds, if any.

    ``memory_limit`` only when the cgroup hit its ceiling after the model last
    saw a tool result: an OOM kill counted by the final observation but not by
    the observation after the last tool call. A test run killed earlier, whose
    result the model saw and recovered from, is in the trajectory and does not
    void the submission.
    """
    if peaks.get("oom_kills", 0) > oom_kills_seen:
        return "memory_limit"
    for key in ("workspace_free_kb", "cache_free_kb"):
        if key in peaks and peaks[key] < EXHAUSTED_FREE_KB:
            return "storage_exhausted"
    return None


@dataclass
class RepositoryAgentClient:
    """Fixed one-attempt loop. A client can run cells sequentially, never concurrently.

    ``writable_prefixes`` is the declared production scope (plus optional
    visible tests). Any other changed path is rejected after capture, and the
    rejected tree is retained as evidence.
    """

    api_key: str | None
    image: str
    runs_root: Path
    model_route: ModelRoute = field(default_factory=ModelRoute)
    completion: TurnCompletion | None = None
    bounds: LoopBounds = field(default_factory=LoopBounds)
    tools: list[dict[str, Any]] = field(default_factory=lambda: deepcopy(TOOLS))
    pilot_tools_by_turn: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    codeintel_query_script: str | None = None
    codeintel_index_mount: str | None = None
    codeintel_index_agent_readable: bool | None = None
    codeintel_max_context_tokens: int = 0
    codeintel_query_limit: int = 0
    system_prompt: str = SYSTEM_PROMPT
    message_prefix: tuple[dict[str, Any], ...] = ()
    writable_prefixes: tuple[str, ...] = ()
    pilot_mode: bool = False
    extension_mode: bool = False
    next_user_turns: tuple[str, ...] = ()
    max_tool_calls_per_turn: int = 0
    max_tool_calls_per_cell: int = 0
    transport: httpx.BaseTransport | None = None
    sandbox_factory: SandboxFactory = DockerTmpfsToolSandbox
    storage_factory: Callable[[Path, int], CellStorage] = DockerTmpfsStagingStorage
    sandbox_limits: SandboxLimits = field(default_factory=SandboxLimits)
    _used_cells: set[str] = field(default_factory=set, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _active_state_lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _active_sandbox: ToolSandbox | None = field(default=None, init=False)
    _active_cell_id: str | None = field(default=None, init=False)

    def cancel_active(self, cell_id: str) -> None:
        with self._active_state_lock:
            sandbox = self._active_sandbox if self._active_cell_id == cell_id else None
        if sandbox is not None:
            sandbox.close()

    def __post_init__(self) -> None:
        if self.extension_mode and self.pilot_mode:
            raise ValueError("extension and pilot modes are mutually exclusive")
        if self.extension_mode and self.tools[:len(EXTENSION_TOOLS)] != EXTENSION_TOOLS:
            raise ValueError("extension mode requires the pinned extension tool prefix")
        if self.model_route.paid_route_reachable:
            if self.completion is not None:
                raise ValueError("the paid route is built in and takes no injected completion")
            if not self.api_key or any(char.isspace() for char in self.api_key):
                raise ValueError("nonblank API key required for the paid route")
            if self.paid_turn_route.endpoint != self.model_route.endpoint:
                raise ValueError("paid turn route differs from the model route")
        else:
            if self.api_key is not None:
                raise ValueError("zero-paid Smithers route must not receive an OpenRouter API key")
            if self.completion is None:
                raise ValueError("the local route requires an injected turn completion")
        if not self.image:
            raise ValueError("locked image identity required")
        turns_ok = 20 <= self.bounds.max_turns <= MAX_MODEL_TURNS
        if not turns_ok or min(asdict(self.bounds).values()) < 1:
            raise ValueError("invalid fixed loop bounds")
        if self.sandbox_limits.storage_mb != self.bounds.max_storage_mb:
            raise ValueError("sandbox storage quota differs from loop storage bound")
        if self.pilot_mode:
            if len(self.next_user_turns) != 2 or not all(
                isinstance(prompt, str) and prompt.strip() for prompt in self.next_user_turns
            ):
                raise ValueError("pilot mode requires two next user turns")
            if self.pilot_tools_by_turn:
                if set(self.pilot_tools_by_turn) != {"T1", "T2_T3"}:
                    raise ValueError("pilot tools require T1 and T2_T3 lists")
                self.pilot_tools_by_turn = deepcopy(self.pilot_tools_by_turn)
            else:
                self.pilot_tools_by_turn = {
                    "T1": deepcopy(PILOT_TOOLS_T1),
                    "T2_T3": deepcopy(PILOT_TOOLS_REVIEW),
                }
            self.tools = self.pilot_tools_by_turn["T1"]
            if not self.writable_prefixes:
                raise ValueError("pilot mode requires writable prefixes")
            if min(self.max_tool_calls_per_turn, self.max_tool_calls_per_cell) < 1:
                raise ValueError("pilot mode requires positive tool call limits")
        elif self.next_user_turns:
            raise ValueError("next user turns require pilot mode")
        elif self.pilot_tools_by_turn:
            raise ValueError("pilot tools require pilot mode")
        if self.max_tool_calls_per_turn < 0 or self.max_tool_calls_per_cell < 0:
            raise ValueError("tool call limits must not be negative")
        if self.codeintel_query_script is not None and (
            not self.codeintel_index_mount or
            min(self.codeintel_max_context_tokens, self.codeintel_query_limit) < 1
        ):
            raise ValueError("incomplete code-intelligence query configuration")
        tool_lists = self.pilot_tools_by_turn.values() if self.pilot_mode else (self.tools,)
        if any(len(_json_bytes(tools)) > self.bounds.max_tool_schema_bytes
               for tools in tool_lists):
            raise ValueError("tool_schema_limit")
        for prefix in self.writable_prefixes:
            if not prefix.endswith("/"):
                raise ValueError("writable prefixes must name directories")
            safe_relative_path(prefix.rstrip("/"))

    @property
    def paid_turn_route(self) -> OpenRouterTurnRoute:
        """The pinned OpenRouter settings for this client's exact model route."""
        return PAID_TURN_ROUTES[(self.model_route.model, self.model_route.provider)]

    @property
    def resolved_config(self) -> ResolvedClientConfig:
        # Direct httpx transport; no provider SDK is instantiated.
        with self._http_client() as client:
            return ResolvedClientConfig(transport_retries=self._transport_retries(client))

    def _http_client(self) -> httpx.Client:
        transport = self.transport or httpx.HTTPTransport(retries=0, trust_env=False)
        return httpx.Client(
            transport=transport, timeout=30, trust_env=False, follow_redirects=False
        )

    @staticmethod
    def _transport_retries(client: httpx.Client) -> int:
        transport = client._transport
        if isinstance(transport, httpx.MockTransport):
            return 0
        if isinstance(transport, httpx.HTTPTransport):
            retries = getattr(getattr(transport, "_pool", None), "_retries", None)
            if type(retries) is int:
                return retries
        raise ValueError("unverifiable_transport_retries")

    def _turn(
        self, messages: list[dict[str, Any]], turn: int, deadline: float | None,
        tools: list[dict[str, Any]], on_dispatch: Callable[[], None] | None = None,
    ) -> ModelTurn:
        if self.completion is not None:
            if on_dispatch is not None:
                on_dispatch()
            return self.completion(
                messages=messages,
                tools=tools,
                max_tokens=self.bounds.max_output_tokens,
                turn=turn,
                deadline=deadline,
            )
        return self._openrouter_turn(
            messages, self.paid_turn_route, tools, deadline=deadline, on_dispatch=on_dispatch
        )

    def _openrouter_turn(
        self, messages: list[dict[str, Any]], route: OpenRouterTurnRoute = HAIKU_TURN_ROUTE,
        tools: list[dict[str, Any]] | None = None,
        *, deadline: float | None = None,
        on_dispatch: Callable[[], None] | None = None,
    ) -> ModelTurn:
        if deadline is not None and deadline <= time.monotonic():
            raise ValueError("agent_deadline")
        body = {
            "model": route.model,
            "messages": messages,
            "tools": self.tools if tools is None else tools,
            "tool_choice": (
                "auto"
                if route.tool_choice == "auto"
                else {"type": "function", "function": {"name": "submit_output"}}
            ),
            "max_tokens": (
                self.bounds.max_output_tokens
                if route.max_output_tokens is None
                else min(self.bounds.max_output_tokens, route.max_output_tokens)
            ),
            "stream": False,
            "provider": {
                "data_collection": "deny",
                "zdr": True,
                "only": [route.provider],
                "order": [route.provider],
                "allow_fallbacks": False,
                "require_parameters": True,
                "max_price": {
                    "prompt": route.max_prompt_price_per_million,
                    "completion": route.max_completion_price_per_million,
                    "request": 0,
                },
            },
        }
        payload = _json_bytes(body)
        request_limit = (
            self.bounds.max_request_bytes
            if route.max_request_body_bytes is None
            else min(self.bounds.max_request_bytes, route.max_request_body_bytes)
        )
        if len(payload) > request_limit:
            raise ValueError("request_limit")
        chat_completions_url = f"{route.endpoint}/chat/completions"
        with self._http_client() as client:
            if self._transport_retries(client) != 0:
                raise ValueError("retry_config_violation")
            timeout_s = (MODEL_REQUEST_SECONDS if deadline is None
                         else min(MODEL_REQUEST_SECONDS, deadline - time.monotonic()))
            if timeout_s <= 0:
                raise ValueError("agent_deadline")
            if on_dispatch is not None:
                on_dispatch()
            chunks = bytearray()
            over_limit = False
            bytes_received = False
            request_started_at = datetime.now(UTC).isoformat()
            try:
                with client.stream(
                    "POST",
                    chat_completions_url,
                    content=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=timeout_s,
                ) as response:
                    if str(response.url) != chat_completions_url:
                        raise ValueError("provider_response")
                    if not response.is_success:
                        error_chunks = bytearray()
                        for chunk in response.iter_bytes():
                            bytes_received = bytes_received or bool(chunk)
                            if deadline is not None and deadline <= time.monotonic():
                                raise InFlightDeadline(bytes_received=bytes_received)
                            error_chunks.extend(chunk[:2048 - len(error_chunks)])
                            if len(error_chunks) == 2048:
                                break
                        raise ProviderResponseFailure(
                            response.status_code,
                            bytes(error_chunks).decode("utf-8", "ignore"),
                            request_started_at,
                            datetime.now(UTC).isoformat(),
                        )
                    for chunk in response.iter_bytes():
                        bytes_received = bytes_received or bool(chunk)
                        if deadline is not None and deadline <= time.monotonic():
                            raise InFlightDeadline(bytes_received=bytes_received)
                        chunks.extend(chunk)
                        if len(chunks) > self.bounds.max_response_bytes:
                            over_limit = True
                            break
            except httpx.HTTPError as error:
                if deadline is not None and timeout_s < MODEL_REQUEST_SECONDS \
                        and deadline <= time.monotonic():
                    raise InFlightDeadline(bytes_received=bytes_received) from error
                raise
            request_ended_at = datetime.now(UTC).isoformat()
        def billed_failure(
            cause: str, usage: Mapping[str, int | float | None], data: Any = None,
        ) -> BilledResponseError:
            choice = data.get("choices") if isinstance(data, dict) else None
            first_choice = choice[0] if isinstance(choice, list) and choice else None
            finish_reason = (
                first_choice.get("finish_reason") if isinstance(first_choice, dict) else None
            )
            return BilledResponseError(cause, usage, {
                "started_at": request_started_at, "ended_at": request_ended_at,
                "generation_id": data.get("id") if isinstance(data, dict)
                and isinstance(data.get("id"), str) else None,
                "http_status": response.status_code,
                "finish_reason": finish_reason,
                "error_body": bytes(chunks[:2048]).decode("utf-8", "ignore"),
                "model_revision": "unavailable",
            })
        try:
            data = json.loads(chunks)
        except (ValueError, UnicodeError) as error:
            cause = "response_limit" if over_limit else "provider_response"
            raise billed_failure(cause, _read_billed_usage(None)) from error
        billed_usage = _read_billed_usage(data)
        if over_limit:
            raise billed_failure("response_limit", billed_usage, data)
        if (
            not isinstance(data, dict)
            or data.get("model") != route.model
            or data.get("provider") != route.provider_name
        ):
            raise billed_failure("provider_identity", billed_usage, data)
        choices, usage = data.get("choices"), data.get("usage")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(usage, dict):
            raise billed_failure("provider_response", billed_usage, data)
        choice = choices[0]
        if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
            raise billed_failure("provider_response", billed_usage, data)
        cost = billed_usage["cost_usd"]
        if cost is None:
            raise billed_failure("provider_usage", billed_usage, data)
        prompt_count = billed_usage["prompt_tokens"]
        completion_count = billed_usage["completion_tokens"]
        if type(prompt_count) is not int or type(completion_count) is not int:
            raise billed_failure("provider_usage", billed_usage, data)
        provider_error = data.get("error")
        error_text = (
            provider_error if isinstance(provider_error, str)
            else json.dumps(provider_error, ensure_ascii=False) if provider_error is not None
            else bytes(chunks).decode("utf-8", "ignore")
            if choice.get("finish_reason") == "error" else None
        )
        return ModelTurn(
            message=choice["message"],
            finish_reason=str(choice.get("finish_reason")),
            prompt_tokens=prompt_count,
            completion_tokens=completion_count,
            cost_usd=float(cost),
            started_at=request_started_at,
            ended_at=request_ended_at,
            generation_id=data.get("id") if isinstance(data.get("id"), str) else None,
            http_status=response.status_code,
            error_body=(error_text.encode("utf-8")[:2048].decode("utf-8", "ignore")
                        if error_text is not None else None),
            model_revision="unavailable",
        )

    def run_cell(
        self, *, cell_id: str, package: Mapping[str, str], deadline: float | None = None,
        cancel_event: threading.Event | None = None,
    ) -> LoopResult:
        if not self._lock.acquire(blocking=False):
            raise AgentLoopError("concurrency_limit", {"events": []})
        try:
            if cell_id in self._used_cells:
                raise AgentLoopError("attempt_limit", {"events": []})
            self._used_cells.add(cell_id)
            return self._run_once(
                cell_id=cell_id, package=package, deadline=deadline,
                cancel_event=cancel_event,
            )
        finally:
            self._lock.release()

    def _observed_work(
        self,
        baseline: Path,
        workspace: Path,
        *,
        enforce_scope: bool = True,
        resource_cause: str | None = None,
    ) -> tuple[bytes, dict[str, bytes], str, str]:
        before = regular_tree(baseline)
        after = regular_tree(workspace)
        if enforce_scope:
            check_submission_scope(before, after, writable_prefixes=self.writable_prefixes)
        # The captured tree's own typed rejections and the scope and tampering
        # checks outrank a resource cause; only an in-scope tree reaches it.
        if resource_cause is not None:
            raise ValueError(resource_cause)
        captured = submission_patch(baseline, workspace)
        return captured.patch, after, captured.baseline_tree_digest, captured.final_tree_digest

    def _run_once(
        self, *, cell_id: str, package: Mapping[str, str], deadline: float | None,
        cancel_event: threading.Event | None,
    ) -> LoopResult:
        trajectory: dict[str, Any] = {
            "events": [],
            "messages": [],
            "turns": [],
            "config": asdict(self.resolved_config),
        }
        if self.codeintel_index_mount is not None:
            trajectory["code_intel_index"] = {
                "path": self.codeintel_index_mount,
                "agent_readable": self.codeintel_index_agent_readable is True,
            }
        events: list[dict[str, Any]] = trajectory["events"]
        instruction = package.get("instruction.md")
        if not isinstance(instruction, str) or not instruction.strip():
            raise AgentLoopError("missing_instruction", trajectory)
        repository = {
            path.removeprefix("workspace/"): content
            for path, content in package.items()
            if path.startswith("workspace/")
        }
        try:
            for path in repository:
                relative = safe_relative_path(path)
                if _FORBIDDEN_REPOSITORY_PARTS.intersection(relative.parts):
                    raise ValueError("forbidden_repository_content")
        except ValueError as error:
            cause = (
                "forbidden_repository_content"
                if str(error) == "forbidden_repository_content"
                else "unsafe_repository_path"
            )
            raise AgentLoopError(cause, trajectory) from error
        cell_root = self.runs_root / uuid.uuid4().hex
        cell_root.mkdir(parents=True, exist_ok=False)
        baseline = cell_root / "baseline"
        baseline.mkdir()
        storage = self.storage_factory(cell_root, self.bounds.max_storage_mb)
        workspace, cache = storage.workspace, storage.cache
        sandbox: ToolSandbox | None = None
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": instruction},
            *self.message_prefix,
        ]
        trajectory["messages"] = deepcopy(messages)

        def record_message(message: dict[str, Any]) -> None:
            messages.append(message)
            trajectory["messages"].append(deepcopy(message))

        prefix_length = len(messages)
        prompt_tokens: int | None = 0
        completion_tokens: int | None = 0
        requests = 0
        cell_tool_calls = 0
        codeintel_queries = 0
        trajectory["limits"] = {
            "max_turns": self.bounds.max_turns,
            "max_tool_calls_per_turn": self.max_tool_calls_per_turn,
            "max_tool_calls_per_cell": self.max_tool_calls_per_cell,
            "codeintel_query_limit": self.codeintel_query_limit,
        }
        logical_turn = 1
        turn_tool_calls = 0
        turn_record: dict[str, Any] = {
            "turn": "T1", "tool_calls": [], "submission": None,
            "workspace_diff": None,
            "tools_turn_sha256": digest_bytes(canonical_json(
                self.pilot_tools_by_turn["T1"] if self.pilot_mode else self.tools)),
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "requests": 0,
                      "cost_usd": 0.0 if self.model_route.paid_route_reachable else None},
        }
        trajectory["turns"].append(turn_record)
        cost_usd: float | None = 0.0 if self.model_route.paid_route_reachable else None
        primary_failed = False
        captured = False
        # The cgroup's OOM-kill count as of the model's last tool result.
        oom_kills_seen = 0

        def usage() -> dict[str, int | float | None]:
            billed: dict[str, int | float | None] = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "requests": requests,
                "cost_usd": cost_usd,
            }
            trajectory["actual_usage"] = {
                **billed, "tool_calls": cell_tool_calls,
                "codeintel_queries": codeintel_queries,
            }
            return billed

        def count_dispatch() -> None:
            nonlocal requests
            requests += 1
            turn_usage: dict[str, int | float | None] = turn_record["usage"]
            turn_usage["requests"] = int(turn_usage["requests"] or 0) + 1

        def accrue_billed(reading: Mapping[str, int | float | None]) -> None:
            nonlocal prompt_tokens, completion_tokens, cost_usd
            turn_usage: dict[str, int | float | None] = turn_record["usage"]
            for key in ("prompt_tokens", "completion_tokens"):
                value = reading.get(key)
                if type(value) is int and value >= 0:
                    if key == "prompt_tokens":
                        if prompt_tokens is not None:
                            prompt_tokens += value
                    else:
                        if completion_tokens is not None:
                            completion_tokens += value
                    turn_count = turn_usage[key]
                    if turn_count is not None:
                        turn_usage[key] = int(turn_count) + value
                else:
                    if key == "prompt_tokens":
                        prompt_tokens = None
                    else:
                        completion_tokens = None
                    turn_usage[key] = None
            billed_cost = reading.get("cost_usd")
            if billed_cost is None:
                cost_usd = None
                turn_usage["cost_usd"] = None
            elif cost_usd is not None:
                cost_usd += float(billed_cost)
                if turn_usage["cost_usd"] is not None:
                    turn_usage["cost_usd"] = float(turn_usage["cost_usd"]) + float(billed_cost)

        def mark_cost_unknown() -> None:
            nonlocal cost_usd
            cost_usd = None
            turn_usage: dict[str, int | float | None] = turn_record["usage"]
            turn_usage["cost_usd"] = None

        def remaining() -> float:
            if cancel_event is not None and cancel_event.is_set():
                raise ValueError("cancelled")
            if deadline is None:
                return MAX_TOOL_SECONDS
            left = deadline - time.monotonic()
            if left <= 0:
                raise ValueError("agent_deadline")
            return min(MAX_TOOL_SECONDS, left)

        def capture() -> dict[str, int]:
            nonlocal captured
            assert sandbox is not None
            peaks = sandbox.capture_workspace()
            captured = True
            if peaks:
                events.append(
                    {"kind": "cgroup_peaks", **peaks, "oom_kills_seen_by_tools": oom_kills_seen}
                )
            return peaks

        def observe_oom_kills(turn: int, tool: str) -> None:
            """Record kills the model can see in this tool's result as recovered."""
            nonlocal oom_kills_seen
            assert sandbox is not None
            total = sandbox.oom_kills()
            if total is not None and total > oom_kills_seen:
                events.append({
                    "kind": "oom_kill", "turn": turn, "tool": tool,
                    "oom_kills": total - oom_kills_seen, "total": total,
                })
                oom_kills_seen = total

        def advance_pilot_turn() -> None:
            nonlocal prefix_length, logical_turn, turn_tool_calls, captured, turn_record
            record_message({"role": "user", "content": self.next_user_turns[logical_turn - 1]})
            prefix_length = len(messages)
            logical_turn += 1
            turn_tool_calls = 0
            captured = False
            turn_record = {
                "turn": f"T{logical_turn}", "tool_calls": [],
                "submission": None, "workspace_diff": None,
                "tools_turn_sha256": digest_bytes(canonical_json(
                    self.pilot_tools_by_turn["T2_T3"])),
                "usage": {"prompt_tokens": 0, "completion_tokens": 0,
                          "requests": 0,
                          "cost_usd": 0.0 if cost_usd is not None else None},
            }
            trajectory["turns"].append(turn_record)

        def pilot_summary() -> str:
            first = trajectory["turns"][0]["submission"]
            return first["title"] if first is not None else ""

        try:
            storage.prepare()
            events.append(
                {"kind": "storage_prepared", "max_storage_mb": self.bounds.max_storage_mb}
            )
            materialize_under(workspace, repository)
            materialize_under(baseline, repository)
            _prepare_container_writes(workspace, cache)
            remaining()
            if self.sandbox_factory is DockerTmpfsToolSandbox:
                sandbox = DockerTmpfsToolSandbox(
                    workspace, cache, self.image, cell_id, limits=self.sandbox_limits
                )
            else:
                sandbox = self.sandbox_factory(workspace, cache, self.image, cell_id)
            with self._active_state_lock:
                self._active_sandbox = sandbox
                self._active_cell_id = cell_id
            events.append(
                {
                    "kind": "sandbox_created",
                    "container": sandbox.name,
                    "workspace": str(workspace),
                    "cache": str(cache),
                    "observed": getattr(sandbox, "observed", None),
                }
            )
            for turn in range(1, self.bounds.max_turns + 1):
                remaining()
                turn_tools = self.pilot_tools_by_turn[
                    "T1" if logical_turn == 1 else "T2_T3"
                ] if self.pilot_mode else self.tools
                turn_record["tools_turn_sha256"] = digest_bytes(canonical_json(turn_tools))
                if len(_json_bytes(turn_tools)) > self.bounds.max_tool_schema_bytes:
                    raise ValueError("tool_schema_limit")
                _shrink_conversation(
                    messages, self.bounds.max_conversation_bytes, events, prefix_length
                )
                if len(_json_bytes(messages)) > self.bounds.max_conversation_bytes:
                    raise ValueError("conversation_limit")
                if self.completion is not None and (
                    len(_json_bytes(messages)) + len(_json_bytes(turn_tools))
                    > self.bounds.max_request_bytes
                ):
                    raise ValueError("request_limit")
                turn_usage: dict[str, int | float | None] = turn_record["usage"]
                started = time.monotonic()
                started_at = datetime.now(UTC).isoformat()
                requests_before = requests
                try:
                    answer = self._turn(messages, turn, deadline, turn_tools, count_dispatch)
                except BilledResponseError as error:
                    accrue_billed(error.usage)
                    events.append({
                        "kind": "model_request", "turn": turn,
                        "prompt_tokens": error.usage.get("prompt_tokens"),
                        "completion_tokens": error.usage.get("completion_tokens"),
                        "finish_reason": error.provenance.get("finish_reason"),
                        "tool_calls": None,
                        "request_bytes": len(_json_bytes(messages)),
                        "seconds": round(time.monotonic() - started, 3),
                        "started_at": error.provenance.get("started_at") or started_at,
                        "ended_at": error.provenance.get("ended_at")
                        or datetime.now(UTC).isoformat(),
                        "generation_id": error.provenance.get("generation_id"),
                        "http_status": error.provenance.get("http_status"),
                        "error_body": error.provenance.get("error_body"),
                        "model_revision": error.provenance.get("model_revision", "unavailable"),
                        "sampling": "unset",
                        "billing": "uncertain" if error.usage.get("cost_usd") is None
                        else "measured",
                        "observations": {},
                    })
                    raise
                except (ValueError, RuntimeError, OSError, httpx.HTTPError) as error:
                    if self.model_route.paid_route_reachable and requests > requests_before:
                        mark_cost_unknown()
                    if isinstance(error, ProviderResponseFailure):
                        events.append({
                            "kind": "model_request", "turn": turn,
                            "prompt_tokens": None, "completion_tokens": None,
                            "finish_reason": None, "tool_calls": None,
                            "request_bytes": len(_json_bytes(messages)),
                            "seconds": round(time.monotonic() - started, 3),
                            "started_at": error.started_at, "ended_at": error.ended_at,
                            "generation_id": None, "http_status": error.status,
                            "error_body": error.body, "model_revision": "unavailable",
                            "sampling": "unset", "billing": "uncertain",
                            "observations": {},
                        })
                    raise
                message = answer.message
                ended_at = datetime.now(UTC).isoformat()
                if (
                    not isinstance(message, dict)
                    or type(answer.prompt_tokens) is not int
                    or type(answer.completion_tokens) is not int
                    or answer.prompt_tokens < 0
                    or answer.completion_tokens < 0
                ):
                    raise ValueError("provider_usage")
                if self.model_route.paid_route_reachable:
                    if answer.cost_usd is None:
                        raise ValueError("provider_usage")
                elif answer.cost_usd is not None:
                    raise ValueError("local_billing_must_be_uncertain")
                if answer.cost_usd is not None:
                    accrue_billed({
                        "prompt_tokens": answer.prompt_tokens,
                        "completion_tokens": answer.completion_tokens,
                        "cost_usd": answer.cost_usd,
                    })
                else:
                    if prompt_tokens is not None:
                        prompt_tokens += answer.prompt_tokens
                    if completion_tokens is not None:
                        completion_tokens += answer.completion_tokens
                    if turn_usage["prompt_tokens"] is not None:
                        turn_usage["prompt_tokens"] = (
                            int(turn_usage["prompt_tokens"]) + answer.prompt_tokens
                        )
                    if turn_usage["completion_tokens"] is not None:
                        turn_usage["completion_tokens"] = (
                            int(turn_usage["completion_tokens"]) + answer.completion_tokens
                        )
                calls = message.get("tool_calls") or []
                events.append({
                    "kind": "model_request", "turn": turn,
                    "prompt_tokens": answer.prompt_tokens,
                    "completion_tokens": answer.completion_tokens,
                    "finish_reason": answer.finish_reason,
                    "tool_calls": len(calls) if isinstance(calls, list) else None,
                    "request_bytes": len(_json_bytes(messages)),
                    "seconds": round(time.monotonic() - started, 3),
                    "started_at": answer.started_at or started_at,
                    "ended_at": answer.ended_at or ended_at,
                    "generation_id": answer.generation_id,
                    "http_status": answer.http_status,
                    "error_body": answer.error_body,
                    "model_revision": answer.model_revision,
                    "sampling": "unset",
                    "billing": "uncertain" if answer.cost_usd is None else "measured",
                    "observations": dict(answer.observations),
                })
                cut_off = (
                    answer.finish_reason == "length"
                    or answer.completion_tokens >= self.bounds.max_output_tokens
                )
                if cut_off:
                    # Kept whole, whatever happens next: it is what tells a
                    # runaway generation from a legitimately long write.
                    content = message.get("content")
                    events.append({
                        "kind": "output_cut_off", "turn": turn,
                        "content": content if isinstance(content, str) else None,
                        "tool_calls": calls,
                    })
                if answer.completion_tokens > self.bounds.max_output_tokens:
                    raise ValueError("output_token_limit")
                if not isinstance(calls, list) or not calls:
                    content = message.get("content")
                    if not cut_off:
                        # The reply that ends the cell is never a message, so
                        # keep its text: a manual read must see what it said.
                        events.append({
                            "kind": "reply_without_tool_call", "turn": turn,
                            "finish_reason": answer.finish_reason,
                            "content": content if isinstance(content, str) else None,
                        })
                    if (answer.finish_reason == "error" or
                            answer.prompt_tokens == answer.completion_tokens == 0):
                        raise ValueError("provider_error")
                    if answer.finish_reason == "length":
                        raise ValueError("output_token_limit")
                    if answer.finish_reason == "stop" and not content:
                        raise ValueError("empty_reply")
                    raise ValueError("no_tool_call")
                replayed = [_replayable_call(call) for call in calls]
                content = message.get("content")
                record_message({
                    "role": "assistant",
                    "content": content if isinstance(content, str) else None,
                    "tool_calls": replayed,
                })
                for call_index, call in enumerate(replayed):
                    remaining()
                    if self.pilot_mode and turn_tool_calls >= self.max_tool_calls_per_turn:
                        for skipped in replayed[call_index:]:
                            record_message({
                                "role": "tool", "tool_call_id": skipped["id"],
                                "content": "turn ended: tool call limit",
                            })
                        break
                    if self.pilot_mode and cell_tool_calls >= self.max_tool_calls_per_cell:
                        raise ValueError("cell_tool_call_limit")
                    turn_tool_calls += 1
                    cell_tool_calls += 1
                    call_id = call["id"]
                    name, raw = call["function"]["name"], call["function"]["arguments"]
                    tool_started = time.monotonic()
                    tool_trace: dict[str, Any] = {
                        "id": call_id, "name": name, "arguments": None,
                        "returned_text": None, "exit_code": None,
                        "seconds": 0.0, "truncated": False,
                    }
                    turn_record["tool_calls"].append(tool_trace)
                    try:
                        arguments = json.loads(raw) if isinstance(raw, str) else raw
                        tool_trace["arguments"] = arguments
                        if not isinstance(name, str) or not isinstance(arguments, dict):
                            raise ToolArgumentError("tool call needs a name and object arguments")
                        if name == "submit_output":
                            submission = _submission(
                                arguments, logical_turn, self.pilot_mode, self.extension_mode
                            )
                            if call_index != len(calls) - 1:
                                raise ToolArgumentError("submit_output must be the last call")
                            events.append({"kind": "submit_requested", "turn": turn})
                            peaks = capture()
                            patch, files, before_digest, after_digest = self._observed_work(
                                baseline, workspace,
                                resource_cause=_resource_cause(peaks, oom_kills_seen),
                            )
                            tool_trace["returned_text"] = "submitted"
                            tool_trace["exit_code"] = 0
                            tool_trace["seconds"] = round(time.monotonic() - tool_started, 3)
                            turn_record["submission"] = submission
                            turn_record["workspace_diff"] = patch.decode("utf-8")
                            turn_record["baseline_tree_digest"] = before_digest
                            turn_record["tree_digest"] = after_digest
                            events.append({"kind": "submitted", "turn": turn})
                            if self.pilot_mode and logical_turn < 3:
                                record_message({
                                    "role": "tool", "tool_call_id": call_id,
                                    "content": "submission recorded",
                                })
                                advance_pilot_turn()
                                break
                            usage()
                            return LoopResult(
                                pilot_summary() if self.pilot_mode else submission["summary"],
                                patch, files, before_digest, after_digest, trajectory,
                                prompt_tokens, completion_tokens, cost_usd, requests,
                            )
                        limit = remaining()
                        try:
                            if name == "codeintel_query":
                                if codeintel_queries >= self.codeintel_query_limit:
                                    raise ToolArgumentError("code-intelligence query limit reached")
                                codeintel_queries += 1
                            output = _execute_tool(
                                sandbox, name, arguments, self.bounds.max_tool_output_bytes,
                                limit,
                                codeintel_query_script=self.codeintel_query_script,
                                codeintel_index_mount=self.codeintel_index_mount,
                                codeintel_max_context_tokens=self.codeintel_max_context_tokens,
                            )
                        except RuntimeError as error:
                            if str(error) != "tool_timeout":
                                raise
                            # A hung command is the model's to notice and fix,
                            # within the cell's remaining budget.
                            sandbox.interrupt()
                            events.append({
                                "kind": "tool_timeout", "turn": turn, "tool": name,
                                "limit_seconds": round(limit, 3),
                            })
                            observe_oom_kills(turn, name)
                            record_message({
                                "role": "tool", "tool_call_id": call_id,
                                "content": (
                                    f"error: command exceeded its {limit:.0f}s limit and every "
                                    "process it started was killed"
                                ),
                            })
                            tool_trace["returned_text"] = messages[-1]["content"]
                            tool_trace["seconds"] = round(time.monotonic() - tool_started, 3)
                            continue
                        observe_oom_kills(turn, name)
                        refused = f"exit={TOOL_REFUSED_EXIT}\n"
                        if name in _SCRIPTED_TOOLS and output.text.startswith(refused):
                            tool_trace["exit_code"] = TOOL_REFUSED_EXIT
                            tool_trace["truncated"] = output.truncated
                            raise ToolArgumentError(output.text.removeprefix(refused).strip())
                    except (ToolArgumentError, json.JSONDecodeError) as error:
                        # The call is the model's mistake, not the harness's:
                        # it sees why and may revise within its turn budget.
                        reason = str(error) or type(error).__name__
                        events.append({
                            "kind": "tool_error", "turn": turn,
                            "tool": name if isinstance(name, str) else None, "reason": reason,
                        })
                        record_message(
                            {"role": "tool", "tool_call_id": call_id, "content": f"error: {reason}"}
                        )
                        tool_trace["returned_text"] = messages[-1]["content"]
                        tool_trace["seconds"] = round(time.monotonic() - tool_started, 3)
                        continue
                    cap = self.bounds.max_tool_output_bytes
                    bounded, bounded_truncated = _bounded_text(output.text, cap)
                    page_truncated = output.page_truncated
                    if output.truncated or bounded_truncated:
                        # The model is told its output was cut, within the same cap.
                        note = (
                            f"\n[output truncated at the {cap}-byte tool output limit; "
                            f"{output.original_bytes} bytes in all]"
                        )
                        kept = cap - len(note.encode("utf-8"))
                        if kept > 0:
                            bounded = _bounded_text(output.text, kept)[0] + note
                        events.append(
                            {
                                "kind": "tool_output_truncated",
                                "turn": turn,
                                "tool": name,
                                "original_bytes": output.original_bytes,
                            }
                        )
                    record_message(
                        {"role": "tool", "tool_call_id": call_id, "content": bounded}
                    )
                    exit_match = re.match(r"exit=(-?\d+)\n", bounded)
                    tool_trace.update({
                        "returned_text": bounded,
                        "exit_code": int(exit_match.group(1)) if exit_match else None,
                        "seconds": round(time.monotonic() - tool_started, 3),
                        "truncated": output.truncated or bounded_truncated or page_truncated,
                        "original_bytes": output.original_bytes,
                    })
                    if name == "read_file":
                        tool_trace["returned_range"] = _read_coverage(
                            arguments, output, output.truncated or bounded_truncated,
                        )
                    if name == "run_command":
                        tool_trace["scope_classification"] = "unclassified"
                    events.append({
                        "kind": "tool_call", "turn": turn, "tool": name,
                        "exit_ok": output.text.startswith("exit=0\n"),
                        "output_bytes": output.original_bytes,
                    })
                if self.pilot_mode and cell_tool_calls >= self.max_tool_calls_per_cell:
                    raise ValueError("cell_tool_call_limit")
                if self.pilot_mode and turn_tool_calls >= self.max_tool_calls_per_turn:
                    peaks = capture()
                    patch, files, before_digest, after_digest = self._observed_work(
                        baseline, workspace,
                        resource_cause=_resource_cause(peaks, oom_kills_seen),
                    )
                    turn_record.update({
                        "stop_cause": "turn_tool_call_limit",
                        "workspace_diff": patch.decode("utf-8"),
                        "patch_ref": digest_bytes(patch),
                        "baseline_tree_digest": before_digest,
                        "tree_digest": after_digest,
                    })
                    events.append({"kind": "turn_stopped", "turn": logical_turn,
                                   "cause": "turn_tool_call_limit"})
                    if logical_turn < 3:
                        advance_pilot_turn()
                        continue
                    raise ValueError("turn_tool_call_limit")
                _shrink_conversation(
                    messages, self.bounds.max_conversation_bytes, events, prefix_length
                )
                if len(_json_bytes(messages)) > self.bounds.max_conversation_bytes:
                    raise ValueError("conversation_limit")
            raise ValueError("turn_limit")
        except (
            ValueError,
            RuntimeError,
            OSError,
            httpx.HTTPError,
            subprocess.SubprocessError,
        ) as error:
            primary_failed = True
            rejection: ArtifactCollectionRejected | None = None
            if isinstance(error, ArtifactCollectionRejected):
                rejection = error
                cause = error.cause
            elif isinstance(error, ModelDispatchError):
                cause = f"model_dispatch:{error.cause}"
            elif isinstance(error, ValueError):
                cause = str(error)
            elif isinstance(error, ContainerStartError):
                cause = "container_start"
                if error.cleanup_failed:
                    events.append({"kind": "cleanup_failed", "cause": "container_cleanup"})
            elif isinstance(error, RuntimeError) and str(error) in {
                "tool_timeout", "cgroup_peak_observation", "workspace_capture"
            }:
                cause = str(error)
            elif isinstance(error, httpx.HTTPError):
                cause = "transport_failure"
            else:
                cause = "sandbox_failure"
            turn_record["stop_cause"] = cause
            stopped: dict[str, Any] = {"kind": "stopped", "cause": cause, "requests": requests}
            if isinstance(error, httpx.HTTPError):
                stopped["error"] = type(error).__name__
            if isinstance(error, InFlightDeadline):
                stopped["request_in_flight"] = True
                stopped["bytes_received"] = error.bytes_received
            events.append(stopped)
            evidence: dict[str, bytes] = {}
            if sandbox is not None and rejection is None:
                # A cell that never submitted still did work. Retain it as
                # evidence of what the model left behind, never as a candidate.
                try:
                    if not captured:
                        capture()
                    patch, _, before_digest, after_digest = self._observed_work(
                        baseline, workspace, enforce_scope=False,
                    )
                    evidence["candidate.patch"] = patch
                    if self.pilot_mode:
                        turn_record.update({
                            "workspace_diff": patch.decode("utf-8"),
                            "patch_ref": digest_bytes(patch),
                            "baseline_tree_digest": before_digest,
                            "tree_digest": after_digest,
                        })
                except (ValueError, RuntimeError, OSError, subprocess.SubprocessError):
                    events.append({"kind": "partial_capture_failed"})
            raise AgentLoopError(
                cause, trajectory, evidence=evidence, rejection=rejection, usage=usage()
            ) from error
        finally:
            cleanup_cause: str | None = None
            try:
                if sandbox is not None:
                    sandbox.close()
            except (RuntimeError, OSError, subprocess.SubprocessError):
                events.append({"kind": "cleanup_failed", "cause": "container_cleanup"})
                cleanup_cause = "container_cleanup"
            with self._active_state_lock:
                self._active_sandbox = None
                self._active_cell_id = None
            try:
                storage.close()
            except (RuntimeError, OSError, subprocess.SubprocessError):
                events.append({"kind": "cleanup_failed", "cause": "storage_cleanup"})
                if cleanup_cause is None:
                    cleanup_cause = "storage_cleanup"
            finally:
                if not storage.mounted:
                    shutil.rmtree(cell_root, ignore_errors=True)
            if cleanup_cause is not None and not primary_failed:
                events.append({"kind": "stopped", "cause": cleanup_cause, "requests": requests})
                raise AgentLoopError(cleanup_cause, trajectory, usage=usage())
