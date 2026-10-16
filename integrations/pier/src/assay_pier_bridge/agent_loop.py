"""One repository-capable agent attempt per cell.

The host owns the model connection. Only a fresh, network-disabled container
touches the cell's repository copy. No evaluator or hidden-test mount is passed
to that container. The fixed tool set is read_file, write_file,
replace_in_file, run_command, and submit_output; each result is returned to
the same cell's conversation.

The paid OpenRouter route is built in. Every other route is a ``TurnCompletion``
the caller injects, so the backend that drives turns is the one whose identity
the caller authorized (for the local fleet, Assay's pinned Smithers client).
"""

from __future__ import annotations

import io
import json
import math
import os
import selectors
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, NoReturn, Protocol

import httpx

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


@dataclass(frozen=True, slots=True)
class OpenRouterTurnRoute:
    """Pinned settings for one authorized repository-agent OpenRouter route."""

    endpoint: str
    model: str
    provider: str
    provider_name: str
    max_prompt_price_per_million: float
    max_completion_price_per_million: float
    max_request_body_bytes: int
    max_output_tokens: int
    tool_choice: Literal["auto", "forced"]


# Preserve the existing repository-agent Haiku request while the frontier
# model and price ceiling await the operator's choice.
HAIKU_TURN_ROUTE = OpenRouterTurnRoute(
    endpoint="https://openrouter.ai/api/v1",
    model=MODEL,
    provider=PROVIDER,
    provider_name=PROVIDER_NAME,
    max_prompt_price_per_million=MAX_PROMPT_PRICE_PER_MILLION,
    max_completion_price_per_million=MAX_COMPLETION_PRICE_PER_MILLION,
    max_request_body_bytes=98_304,
    max_output_tokens=8_192,
    tool_choice="auto",
)


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
    prompt_tokens: int
    completion_tokens: int
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
        *,
        tmpfs_storage: bool = False,
        limits: SandboxLimits | None = None,
    ) -> None:
        limits = limits or SandboxLimits()
        self.name = f"assay-agent-{uuid.uuid4().hex}"
        self._closed = False
        self._workspace = workspace
        self._tmpfs_storage = tmpfs_storage
        mounts = (
            [
                "--tmpfs", f"/workspace:size={limits.workspace_mb}m,mode=1777",
                "--tmpfs", f"/cache:size={limits.cache_mb}m,mode=1777",
            ]
            if tmpfs_storage
            else ["-v", f"{workspace}:/workspace:rw", "-v", f"{cache}:/cache:rw"]
        )
        command = [
            "docker",
            "run",
            "-d",
            "--name",
            self.name,
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
            ["docker", "exec", self.name, "tar", "-c", "-f", "-", "-C", "/workspace", "."],
            capture_output=True, timeout=60, check=False,
        )
        if archived.returncode:
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
        if not self._closed:
            self._closed = True
            removed = subprocess.run(
                ["docker", "rm", "-f", self.name],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if removed.returncode:
                raise RuntimeError("container_cleanup")


class DockerTmpfsToolSandbox(DockerToolSandbox):
    """The declared local sandbox: Docker-enforced tmpfs quotas, no host privileges."""

    def __init__(
        self, workspace: Path, cache: Path, image: str, *, limits: SandboxLimits | None = None
    ) -> None:
        super().__init__(workspace, cache, image, tmpfs_storage=True, limits=limits)


SandboxFactory = Callable[[Path, Path, str], ToolSandbox]


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
_FORBIDDEN_REPOSITORY_PARTS = frozenset({"hidden_tests", "hidden-tests", "reference_solutions"})
# Causes that end a cell because of what the model did, not the harness.
CANDIDATE_STOP_CAUSES = frozenset(
    {
        "turn_limit",
        "no_tool_call",
        "invalid_tool_call",
        "invalid_submission",
        "output_token_limit",
        "conversation_limit",
        "request_limit",
    }
)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _bounded_text(text: str, limit: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text, False
    return encoded[:limit].decode("utf-8", errors="ignore"), True


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


def _execute_tool(
    sandbox: ToolSandbox,
    name: str,
    arguments: dict[str, Any],
    max_output_bytes: int,
    timeout_s: float,
) -> ToolOutput:
    if name == "read_file" and set(arguments) <= {"path", "start_line", "end_line"}:
        start = _line_number(arguments, "start_line") or 1
        end = _line_number(arguments, "end_line")
        if end is not None and end < start:
            raise ToolArgumentError("end_line must not be before start_line")
        # The script's page budget leaves room for the sandbox's exit prefix.
        budget = max_output_bytes - len(f"exit={TOOL_REFUSED_EXIT}\n")
        return sandbox.execute(
            ["python", "-c", _READ_FILE, _relative_path(arguments), str(start), str(end or 0),
             str(budget)],
            max_output_bytes=max_output_bytes,
            timeout_s=timeout_s,
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
_SCRIPTED_TOOLS = frozenset({"read_file", "replace_in_file"})


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
    system_prompt: str = SYSTEM_PROMPT
    message_prefix: tuple[dict[str, Any], ...] = ()
    writable_prefixes: tuple[str, ...] = ()
    transport: httpx.BaseTransport | None = None
    sandbox_factory: SandboxFactory = DockerToolSandbox
    storage_factory: Callable[[Path, int], CellStorage] = QuotaCellStorage
    _used_cells: set[str] = field(default_factory=set, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def __post_init__(self) -> None:
        if self.model_route.paid_route_reachable:
            if self.completion is not None:
                raise ValueError("the paid route is built in and takes no injected completion")
            if not self.api_key or any(char.isspace() for char in self.api_key):
                raise ValueError("nonblank API key required for the paid route")
        else:
            if self.api_key is not None:
                raise ValueError("zero-paid Smithers route must not receive an OpenRouter API key")
            if self.completion is None:
                raise ValueError("the local route requires an injected turn completion")
        if not self.image:
            raise ValueError("locked image identity required")
        if self.bounds.max_turns != 20 or min(asdict(self.bounds).values()) < 1:
            raise ValueError("invalid fixed loop bounds")
        if len(_json_bytes(self.tools)) > self.bounds.max_tool_schema_bytes:
            raise ValueError("tool_schema_limit")
        for prefix in self.writable_prefixes:
            if not prefix.endswith("/"):
                raise ValueError("writable prefixes must name directories")
            safe_relative_path(prefix.rstrip("/"))

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
        self, messages: list[dict[str, Any]], turn: int, deadline: float | None
    ) -> ModelTurn:
        if self.completion is not None:
            return self.completion(
                messages=messages,
                tools=self.tools,
                max_tokens=self.bounds.max_output_tokens,
                turn=turn,
                deadline=deadline,
            )
        return self._openrouter_turn(messages, HAIKU_TURN_ROUTE)

    def _openrouter_turn(
        self, messages: list[dict[str, Any]], route: OpenRouterTurnRoute
    ) -> ModelTurn:
        body = {
            "model": route.model,
            "messages": messages,
            "tools": self.tools,
            "tool_choice": (
                "auto"
                if route.tool_choice == "auto"
                else {"type": "function", "function": {"name": "submit_output"}}
            ),
            "max_tokens": min(self.bounds.max_output_tokens, route.max_output_tokens),
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
        if len(payload) > min(self.bounds.max_request_bytes, route.max_request_body_bytes):
            raise ValueError("request_limit")
        chat_completions_url = f"{route.endpoint}/chat/completions"
        with self._http_client() as client:
            if self._transport_retries(client) != 0:
                raise ValueError("retry_config_violation")
            with client.stream(
                "POST",
                chat_completions_url,
                content=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            ) as response:
                if str(response.url) != chat_completions_url or not response.is_success:
                    raise ValueError("provider_response")
                chunks = bytearray()
                for chunk in response.iter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > self.bounds.max_response_bytes:
                        raise ValueError("response_limit")
        data = json.loads(chunks)
        if (
            not isinstance(data, dict)
            or data.get("model") != route.model
            or data.get("provider") != route.provider_name
        ):
            raise ValueError("provider_identity")
        choices, usage = data.get("choices"), data.get("usage")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(usage, dict):
            raise ValueError("provider_response")
        choice = choices[0]
        if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
            raise ValueError("provider_response")
        cost = usage.get("cost")
        if (
            isinstance(cost, bool)
            or not isinstance(cost, (int, float))
            or not math.isfinite(cost)
            or cost < 0
        ):
            raise ValueError("provider_usage")
        for key in ("prompt_tokens", "completion_tokens"):
            if type(usage.get(key)) is not int or usage[key] < 0:
                raise ValueError("provider_usage")
        return ModelTurn(
            message=choice["message"],
            finish_reason=str(choice.get("finish_reason")),
            prompt_tokens=usage["prompt_tokens"],
            completion_tokens=usage["completion_tokens"],
            cost_usd=float(cost),
        )

    def run_cell(
        self, *, cell_id: str, package: Mapping[str, str], deadline: float | None = None
    ) -> LoopResult:
        if not self._lock.acquire(blocking=False):
            raise AgentLoopError("concurrency_limit", {"events": []})
        try:
            if cell_id in self._used_cells:
                raise AgentLoopError("attempt_limit", {"events": []})
            self._used_cells.add(cell_id)
            return self._run_once(package=package, deadline=deadline)
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

    def _run_once(self, *, package: Mapping[str, str], deadline: float | None) -> LoopResult:
        trajectory: dict[str, Any] = {
            "events": [],
            "messages": [],
            "config": asdict(self.resolved_config),
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
        prefix_length = len(messages)
        prompt_tokens = completion_tokens = requests = 0
        cost_usd: float | None = 0.0 if self.model_route.paid_route_reachable else None
        primary_failed = False
        captured = False
        # The cgroup's OOM-kill count as of the model's last tool result.
        oom_kills_seen = 0

        def usage() -> dict[str, int | float | None]:
            return {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "requests": requests,
                "cost_usd": cost_usd,
            }

        def remaining() -> float:
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

        try:
            storage.prepare()
            events.append(
                {"kind": "storage_prepared", "max_storage_mb": self.bounds.max_storage_mb}
            )
            materialize_under(workspace, repository)
            materialize_under(baseline, repository)
            _prepare_container_writes(workspace, cache)
            sandbox = self.sandbox_factory(workspace, cache, self.image)
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
                _shrink_conversation(
                    messages, self.bounds.max_conversation_bytes, events, prefix_length
                )
                if len(_json_bytes(messages)) > self.bounds.max_conversation_bytes:
                    raise ValueError("conversation_limit")
                if len(_json_bytes(messages)) + len(_json_bytes(self.tools)) > (
                    self.bounds.max_request_bytes
                ):
                    raise ValueError("request_limit")
                requests += 1  # Count a failed dispatch; never retry it.
                started = time.monotonic()
                answer = self._turn(messages, turn, deadline)
                message = answer.message
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
                prompt_tokens += answer.prompt_tokens
                completion_tokens += answer.completion_tokens
                if cost_usd is not None and answer.cost_usd is not None:
                    cost_usd += answer.cost_usd
                calls = message.get("tool_calls") or []
                events.append({
                    "kind": "model_request", "turn": turn,
                    "prompt_tokens": answer.prompt_tokens,
                    "completion_tokens": answer.completion_tokens,
                    "finish_reason": answer.finish_reason,
                    "tool_calls": len(calls) if isinstance(calls, list) else None,
                    "request_bytes": len(_json_bytes(messages)),
                    "seconds": round(time.monotonic() - started, 3),
                    "billing": "uncertain" if answer.cost_usd is None else "measured",
                    **answer.observations,
                })
                if (
                    answer.finish_reason == "length"
                    or answer.completion_tokens >= self.bounds.max_output_tokens
                ):
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
                    raise ValueError(
                        "output_token_limit" if answer.finish_reason == "length"
                        else "no_tool_call"
                    )
                replayed = [_replayable_call(call) for call in calls]
                content = message.get("content")
                messages.append({
                    "role": "assistant",
                    "content": content if isinstance(content, str) else None,
                    "tool_calls": replayed,
                })
                for call_index, call in enumerate(replayed):
                    call_id = call["id"]
                    name, raw = call["function"]["name"], call["function"]["arguments"]
                    try:
                        arguments = json.loads(raw) if isinstance(raw, str) else raw
                        if not isinstance(name, str) or not isinstance(arguments, dict):
                            raise ToolArgumentError("tool call needs a name and object arguments")
                        if name == "submit_output":
                            summary = arguments.get("summary")
                            if set(arguments) != {"summary"} or not isinstance(summary, str):
                                raise ToolArgumentError("submit_output takes only a summary")
                            if call_index != len(calls) - 1:
                                raise ToolArgumentError("submit_output must be the last call")
                            events.append({"kind": "submit_requested", "turn": turn})
                            peaks = capture()
                            patch, files, before_digest, after_digest = self._observed_work(
                                baseline, workspace,
                                resource_cause=_resource_cause(peaks, oom_kills_seen),
                            )
                            trajectory["messages"] = messages
                            events.append({"kind": "submitted", "turn": turn})
                            return LoopResult(
                                summary,
                                patch,
                                files,
                                before_digest,
                                after_digest,
                                trajectory,
                                prompt_tokens,
                                completion_tokens,
                                cost_usd,
                                requests,
                            )
                        limit = remaining()
                        try:
                            output = _execute_tool(
                                sandbox, name, arguments, self.bounds.max_tool_output_bytes,
                                limit,
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
                            messages.append({
                                "role": "tool", "tool_call_id": call_id,
                                "content": (
                                    f"error: command exceeded its {limit:.0f}s limit and every "
                                    "process it started was killed"
                                ),
                            })
                            continue
                        observe_oom_kills(turn, name)
                        refused = f"exit={TOOL_REFUSED_EXIT}\n"
                        if name in _SCRIPTED_TOOLS and output.text.startswith(refused):
                            raise ToolArgumentError(output.text.removeprefix(refused).strip())
                    except (ToolArgumentError, json.JSONDecodeError) as error:
                        # The call is the model's mistake, not the harness's:
                        # it sees why and may revise within its turn budget.
                        reason = str(error) or type(error).__name__
                        events.append({
                            "kind": "tool_error", "turn": turn,
                            "tool": name if isinstance(name, str) else None, "reason": reason,
                        })
                        messages.append(
                            {"role": "tool", "tool_call_id": call_id, "content": f"error: {reason}"}
                        )
                        continue
                    cap = self.bounds.max_tool_output_bytes
                    bounded, bounded_truncated = _bounded_text(output.text, cap)
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
                    messages.append(
                        {"role": "tool", "tool_call_id": call_id, "content": bounded}
                    )
                    events.append({
                        "kind": "tool_call", "turn": turn, "tool": name,
                        "exit_ok": output.text.startswith("exit=0\n"),
                        "output_bytes": output.original_bytes,
                    })
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
            trajectory["messages"] = messages
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
            events.append({"kind": "stopped", "cause": cause, "requests": requests})
            evidence: dict[str, bytes] = {}
            if sandbox is not None and rejection is None:
                # A cell that never submitted still did work. Retain it as
                # evidence of what the model left behind, never as a candidate.
                try:
                    if not captured:
                        capture()
                    patch = self._observed_work(baseline, workspace, enforce_scope=False)[0]
                    evidence["candidate.patch"] = patch
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
