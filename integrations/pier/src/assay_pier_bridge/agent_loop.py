"""One repository-capable agent attempt per cell.

The host owns the model connection. Only a fresh, network-disabled container
touches the cell's repository copy. No evaluator or hidden-test mount is passed
to that container. The fixed tool set is read_file, write_file, run_command,
and submit_output; each result is returned to the same cell's conversation.
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
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn, Protocol

import httpx

from assay_pier_bridge.paths import materialize_under, safe_relative_path, submission_patch
from assay_pier_bridge.protocol import ModelRoute
from assay_pier_bridge.provider import (
    CHAT_COMPLETIONS_URL,
    MAX_COMPLETION_PRICE_PER_MILLION,
    MAX_PROMPT_PRICE_PER_MILLION,
    MODEL,
    PROVIDER,
    PROVIDER_NAME,
)

SYSTEM_PROMPT = (
    "You are editing one repository copy in /workspace. Use read_file, write_file, "
    "and run_command to inspect, edit, and check it. Finish with submit_output. "
    "Only this cell's repository is available; hidden tests and reference answers "
    "are never available. Do not seek network access or install packages."
)


@dataclass(frozen=True, slots=True)
class LoopBounds:
    """Ceilings exercised by the measured wf-12 repository-agent run."""

    max_turns: int = 20
    max_tool_schema_bytes: int = 16_384
    max_tool_output_bytes: int = 16_384
    max_conversation_bytes: int = 262_144
    max_request_bytes: int = 327_680
    max_response_bytes: int = 65_536
    max_output_tokens: int = 2_048
    max_storage_mb: int = 512


@dataclass(frozen=True, slots=True)
class ResolvedClientConfig:
    transport_retries: int
    attempts: int = 1
    concurrency: int = 1
    provider_retries: int = 0
    sdk_retries: int = 0


@dataclass(frozen=True, slots=True)
class LoopResult:
    source: str
    patch: bytes
    trajectory: dict[str, Any]
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float | None
    requests: int


class AgentLoopError(RuntimeError):
    """A trial ended at a named boundary; trajectory survives the failure."""

    def __init__(self, cause: str, trajectory: dict[str, Any]) -> None:
        self.cause = cause
        self.trajectory = trajectory
        super().__init__(cause)


class ToolSandbox(Protocol):
    name: str

    def execute(
        self, argv: list[str], *, max_output_bytes: int, input_text: str | None = None
    ) -> ToolOutput: ...
    def capture_workspace(self) -> dict[str, int]: ...
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
        if max_storage_mb != 512:
            raise ValueError("Docker tmpfs qualification requires the pinned 512 MiB bound")
        self.workspace = cell_root / "staging" / "workspace"
        self.cache = cell_root / "staging" / "cache"
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


class DockerToolSandbox:
    """Disposable container with only the neutral repository and cache mounts."""

    def __init__(
        self, workspace: Path, cache: Path, image: str, *, tmpfs_storage: bool = False
    ) -> None:
        self.name = f"assay-agent-{uuid.uuid4().hex}"
        self._closed = False
        self._workspace = workspace
        self._tmpfs_storage = tmpfs_storage
        mounts = (
            [
                "--tmpfs", "/workspace:size=256m,mode=1777",
                "--tmpfs", "/cache:size=256m,mode=1777",
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
            "/tmp",
            "--env",
            "HOME=/cache",
            "--env",
            "XDG_CACHE_HOME=/cache",
            "--env",
            "NPM_CONFIG_CACHE=/cache/npm",
            "--user",
            "1000:1000",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "64",
            "--memory",
            "1024m" if tmpfs_storage else "512m",
            "--cpus",
            "1",
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
            archive = io.BytesIO()
            with tarfile.open(fileobj=archive, mode="w") as stream:
                for path in sorted(workspace.rglob("*")):
                    stream.add(path, arcname=path.relative_to(workspace), recursive=False)
            copied = subprocess.run(
                ["docker", "exec", "-i", self.name, "tar", "-x", "-C", "/workspace"],
                input=archive.getvalue(), capture_output=True, timeout=30, check=False,
            )
            if copied.returncode:
                self._failed_start(copied.returncode)

    def capture_workspace(self) -> dict[str, int]:
        if not self._tmpfs_storage:
            return {}
        peaks = self.execute(
            ["cat", "/sys/fs/cgroup/memory.peak", "/sys/fs/cgroup/pids.peak"],
            max_output_bytes=1024,
        )
        values = peaks.text.splitlines()
        if len(values) != 3 or values[0] != "exit=0":
            raise RuntimeError("cgroup_peak_observation")
        try:
            memory_peak, pids_peak = int(values[1]), int(values[2])
        except ValueError as error:
            raise RuntimeError("cgroup_peak_observation") from error
        copied = subprocess.run(
            ["docker", "cp", f"{self.name}:/workspace/.", str(self._workspace)],
            capture_output=True, text=True, timeout=30, check=False,
        )
        if copied.returncode:
            raise RuntimeError("workspace_capture")
        return {"memory_peak_bytes": memory_peak, "pids_peak": pids_peak}

    def _failed_start(self, returncode: int, *, cause: Exception | None = None) -> NoReturn:
        cleanup_failed = False
        try:
            self.close()
        except (RuntimeError, OSError, subprocess.SubprocessError):
            cleanup_failed = True
        raise ContainerStartError(returncode, cleanup_failed=cleanup_failed) from cause

    def execute(
        self, argv: list[str], *, max_output_bytes: int, input_text: str | None = None
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
            deadline = time.monotonic() + 120
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
    """Qualification sandbox with a real 512 MiB Docker-enforced writable cap."""

    def __init__(self, workspace: Path, cache: Path, image: str) -> None:
        super().__init__(workspace, cache, image, tmpfs_storage=True)


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


TOOLS = [
    _tool("read_file", "Read a repository file by relative path.", {"path": {"type": "string"}}),
    _tool(
        "write_file",
        "Write a repository file by relative path.",
        {
            "path": {"type": "string"},
            "content": {"type": "string"},
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
        "Finish this attempt with the final source text.",
        {
            "source": {"type": "string"},
        },
    ),
]
_FORBIDDEN_REPOSITORY_PARTS = frozenset({"hidden_tests", "hidden-tests", "reference_solutions"})


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


def _relative_path(arguments: dict[str, Any]) -> str:
    path = arguments.get("path")
    if not isinstance(path, str):
        raise ValueError("path must be a string")
    return safe_relative_path(path).as_posix()


def _execute_tool(
    sandbox: ToolSandbox, name: str, arguments: dict[str, Any], max_output_bytes: int
) -> ToolOutput:
    if name == "read_file" and set(arguments) == {"path"}:
        return sandbox.execute(
            ["cat", "--", f"/workspace/{_relative_path(arguments)}"],
            max_output_bytes=max_output_bytes,
        )
    if name == "write_file" and set(arguments) == {"path", "content"}:
        content = arguments["content"]
        if not isinstance(content, str):
            raise ValueError("content must be a string")
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
        )
    if name == "run_command" and set(arguments) == {"command"}:
        command = arguments["command"]
        if not isinstance(command, str) or len(command.encode("utf-8")) > 8_192:
            raise ValueError("command must be a string of at most 8192 bytes")
        return sandbox.execute(["sh", "-lc", command], max_output_bytes=max_output_bytes)
    raise ValueError("unknown tool or argument field")


def _shrink_conversation(
    messages: list[dict[str, Any]], limit: int, events: list[dict[str, Any]]
) -> None:
    """Remove oldest completed tool exchanges; retain system and task messages."""
    while len(_json_bytes(messages)) > limit and len(messages) > 2:
        # A completed exchange is an assistant tool-call message plus its tool results.
        if messages[2].get("role") != "assistant":
            raise ValueError("conversation has no removable tool exchange")
        removed = 1
        while 2 + removed < len(messages) and messages[2 + removed].get("role") == "tool":
            removed += 1
        if 2 + removed == len(messages):
            break  # The latest exchange must remain available to the model.
        del messages[2 : 2 + removed]
        events.append({"kind": "conversation_truncated", "messages_removed": removed})


@dataclass
class RepositoryAgentClient:
    """Fixed one-attempt loop. A client can run cells sequentially, never concurrently."""

    api_key: str | None
    image: str
    runs_root: Path
    model_route: ModelRoute = field(default_factory=ModelRoute)
    bounds: LoopBounds = field(default_factory=LoopBounds)
    transport: httpx.BaseTransport | None = None
    sandbox_factory: SandboxFactory = DockerToolSandbox
    storage_factory: Callable[[Path, int], CellStorage] = QuotaCellStorage
    _used_cells: set[str] = field(default_factory=set, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def __post_init__(self) -> None:
        if self.model_route.paid_route_reachable and (
            not self.api_key or any(char.isspace() for char in self.api_key)
        ):
            raise ValueError("nonblank API key required for the paid route")
        if not self.model_route.paid_route_reachable and self.api_key is not None:
            raise ValueError("zero-paid Smithers route must not receive an OpenRouter API key")
        if not self.image:
            raise ValueError("locked image identity required")
        if self.bounds.max_turns != 20 or min(asdict(self.bounds).values()) < 1:
            raise ValueError("invalid fixed loop bounds")
        if len(_json_bytes(TOOLS)) > self.bounds.max_tool_schema_bytes:
            raise ValueError("tool_schema_limit")

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

    def _completion(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.model_route.paid_route_reachable:
            return self._smithers_completion(messages)
        body = {
            "model": MODEL,
            "messages": messages,
            "tools": TOOLS,
            "tool_choice": "auto",
            "max_tokens": self.bounds.max_output_tokens,
            "stream": False,
            "provider": {
                "data_collection": "deny",
                "zdr": True,
                "only": [PROVIDER],
                "order": [PROVIDER],
                "allow_fallbacks": False,
                "require_parameters": True,
                "max_price": {
                    "prompt": MAX_PROMPT_PRICE_PER_MILLION,
                    "completion": MAX_COMPLETION_PRICE_PER_MILLION,
                    "request": 0,
                },
            },
        }
        payload = _json_bytes(body)
        if len(payload) > self.bounds.max_request_bytes:
            raise ValueError("request_limit")
        with self._http_client() as client:
            if self._transport_retries(client) != 0:
                raise ValueError("retry_config_violation")
            with client.stream(
                "POST",
                CHAT_COMPLETIONS_URL,
                content=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            ) as response:
                if str(response.url) != CHAT_COMPLETIONS_URL or not response.is_success:
                    raise ValueError("provider_response")
                chunks = bytearray()
                for chunk in response.iter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > self.bounds.max_response_bytes:
                        raise ValueError("response_limit")
        data = json.loads(chunks)
        if (
            not isinstance(data, dict)
            or data.get("model") != MODEL
            or data.get("provider") != PROVIDER_NAME
        ):
            raise ValueError("provider_identity")
        return data

    def _smithers_completion(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """Submit one local job per turn; no paid URL or credential is reachable."""
        payload = {
            "messages": messages,
            # A local qualification must observe at least one real tool result
            # before it can submit; otherwise a model can declare success in
            # the same turn as a failed install or test command.
            "tools": TOOLS if len(messages) > 2 else TOOLS[:-1],
            "tool_choice": "required",
            "max_tokens": self.bounds.max_output_tokens,
        }
        if len(_json_bytes(payload)) > self.bounds.max_request_bytes:
            raise ValueError("request_limit")
        submission = {
            "task_type": "inference",
            "payload": payload,
            "requester": "assay-wf12-qualification",
            "model": self.model_route.model,
            "machine": "mcbain",
            "timeout_seconds": 900,
            "max_retries": 0,
            "idempotency_key": f"assay-wf12:{uuid.uuid4().hex}",
        }
        with self._http_client() as client:
            if self._transport_retries(client) != 0:
                raise ValueError("retry_config_violation")
            response = client.post(f"{self.model_route.endpoint}/jobs", json=submission)
            response.raise_for_status()
            job_id = response.json().get("job_id")
            if not isinstance(job_id, str) or not job_id:
                raise ValueError("smithers_job_id")
            deadline = time.monotonic() + 900
            while time.monotonic() < deadline:
                response = client.get(f"{self.model_route.endpoint}/jobs/{job_id}")
                response.raise_for_status()
                job = response.json()
                if (
                    job.get("job_id") != job_id
                    or job.get("model") != self.model_route.model
                    or job.get("machine") != "mcbain"
                ):
                    raise ValueError("smithers_identity")
                if job.get("status") == "complete":
                    break
                if job.get("status") in ("failed", "cancelled"):
                    raise ValueError("smithers_job_failed")
                if job.get("status") not in ("queued", "waking_machine", "dispatched", "running"):
                    raise ValueError("smithers_status")
                time.sleep(0.5)
            else:
                raise ValueError("smithers_deadline")
        result = job.get("result")
        if not isinstance(result, dict):
            raise ValueError("smithers_result")
        # Dispatch's JobResponse currently drops TaskStatusResponse.usage.
        # Read the completed worker task instead of turning missing counts
        # into zeros (which would make the qualification unpublishable).
        with self._http_client() as client:
            worker_response = client.get(f"http://mcbain:8901/tasks/{job_id}")
            worker_response.raise_for_status()
            worker_task = worker_response.json()
        if worker_task.get("job_id") != job_id or worker_task.get("status") != "complete":
            raise ValueError("smithers_worker_identity")
        usage = worker_task.get("usage")
        if not isinstance(usage, dict):
            raise ValueError("smithers_usage_missing")
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        if type(input_tokens) is not int or type(output_tokens) is not int:
            raise ValueError("smithers_usage_missing")
        try:
            created = datetime.fromisoformat(job["created_at"])
            started = datetime.fromisoformat(job["started_at"])
            completed = datetime.fromisoformat(job["completed_at"])
            queue_latency = (started - created).total_seconds()
            wall_seconds = (completed - started).total_seconds()
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("smithers_timing_missing") from error
        if queue_latency < 0 or wall_seconds < 0:
            raise ValueError("smithers_timing_invalid")
        calls = result.get("tool_calls")
        message = {"role": "assistant", "content": result.get("content"), "tool_calls": calls}
        return {
            "choices": [{"finish_reason": "tool_calls" if calls else "stop", "message": message}],
            "usage": {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "cost": None,
            },
            "smithers_job_id": job_id,
            "smithers_created_at": job.get("created_at"),
            "smithers_started_at": job.get("started_at"),
            "smithers_completed_at": job.get("completed_at"),
            "queue_latency_seconds": queue_latency,
            "wall_seconds": wall_seconds,
        }

    def run_cell(self, *, cell_id: str, package: Mapping[str, str]) -> LoopResult:
        if not self._lock.acquire(blocking=False):
            raise AgentLoopError("concurrency_limit", {"events": []})
        try:
            if cell_id in self._used_cells:
                raise AgentLoopError("attempt_limit", {"events": []})
            self._used_cells.add(cell_id)
            return self._run_once(package=package)
        finally:
            self._lock.release()

    def _run_once(self, *, package: Mapping[str, str]) -> LoopResult:
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
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": instruction},
        ]
        prompt_tokens = completion_tokens = requests = 0
        cost_usd: float | None = 0.0 if self.model_route.paid_route_reachable else None
        primary_failed = False
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
                }
            )
            for turn in range(1, self.bounds.max_turns + 1):
                _shrink_conversation(messages, self.bounds.max_conversation_bytes, events)
                if len(_json_bytes(messages)) > self.bounds.max_conversation_bytes:
                    raise ValueError("conversation_limit")
                requests += 1  # Count a failed HTTP dispatch; never retry it.
                data = self._completion(messages)
                choices, usage = data.get("choices"), data.get("usage")
                if (
                    not isinstance(choices, list)
                    or len(choices) != 1
                    or not isinstance(usage, dict)
                ):
                    raise ValueError("provider_response")
                choice = choices[0]
                if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
                    raise ValueError("provider_response")
                message = choice["message"]
                for key in ("prompt_tokens", "completion_tokens"):
                    if type(usage.get(key)) is not int or usage[key] < 0:
                        raise ValueError("provider_usage")
                cost = usage.get("cost")
                if self.model_route.paid_route_reachable:
                    if (
                        isinstance(cost, bool)
                        or not isinstance(cost, (int, float))
                        or not math.isfinite(cost)
                        or cost < 0
                    ):
                        raise ValueError("provider_usage")
                elif cost is not None:
                    raise ValueError("local_billing_must_be_uncertain")
                if usage["completion_tokens"] > self.bounds.max_output_tokens:
                    raise ValueError("output_token_limit")
                prompt_tokens += usage["prompt_tokens"]
                completion_tokens += usage["completion_tokens"]
                if cost_usd is not None:
                    assert isinstance(cost, (int, float))
                    cost_usd += cost
                events.append({
                    "kind": "model_request", "turn": turn,
                    "prompt_tokens": usage["prompt_tokens"],
                    "completion_tokens": usage["completion_tokens"],
                    "billing": "uncertain" if cost is None else "measured",
                    "smithers_job_id": data.get("smithers_job_id"),
                    "smithers_created_at": data.get("smithers_created_at"),
                    "smithers_started_at": data.get("smithers_started_at"),
                    "smithers_completed_at": data.get("smithers_completed_at"),
                    "queue_latency_seconds": data.get("queue_latency_seconds"),
                    "wall_seconds": data.get("wall_seconds"),
                })
                calls = message.get("tool_calls")
                if (
                    choice.get("finish_reason") != "tool_calls"
                    or not isinstance(calls, list)
                    or not calls
                ):
                    raise ValueError("no_tool_call")
                messages.append(message)
                for call_index, call in enumerate(calls):
                    if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
                        raise ValueError("invalid_tool_call")
                    function = call["function"]
                    name, raw = function.get("name"), function.get("arguments")
                    if (
                        not isinstance(name, str)
                        or not isinstance(raw, str)
                        or not isinstance(call.get("id"), str)
                    ):
                        raise ValueError("invalid_tool_call")
                    arguments = json.loads(raw)
                    if not isinstance(arguments, dict):
                        raise ValueError("invalid_tool_call")
                    if name == "submit_output":
                        if (
                            set(arguments) != {"source"}
                            or not isinstance(arguments["source"], str)
                            or call_index != len(calls) - 1
                        ):
                            raise ValueError("invalid_submission")
                        _shrink_conversation(messages, self.bounds.max_conversation_bytes, events)
                        if len(_json_bytes(messages)) > self.bounds.max_conversation_bytes:
                            raise ValueError("conversation_limit")
                        peaks = sandbox.capture_workspace()
                        if peaks:
                            events.append({"kind": "cgroup_peaks", **peaks})
                        patch = submission_patch(baseline, workspace).patch
                        trajectory["messages"] = messages
                        events.append({"kind": "submitted", "turn": turn})
                        return LoopResult(
                            arguments["source"],
                            patch,
                            trajectory,
                            prompt_tokens,
                            completion_tokens,
                            cost_usd,
                            requests,
                        )
                    try:
                        output = _execute_tool(
                            sandbox, name, arguments, self.bounds.max_tool_output_bytes
                        )
                    except ValueError as error:
                        raise ValueError("invalid_tool_call") from error
                    bounded, bounded_truncated = _bounded_text(
                        output.text, self.bounds.max_tool_output_bytes
                    )
                    if output.truncated or bounded_truncated:
                        events.append(
                            {
                                "kind": "tool_output_truncated",
                                "turn": turn,
                                "tool": name,
                                "original_bytes": output.original_bytes,
                            }
                        )
                    messages.append(
                        {"role": "tool", "tool_call_id": call["id"], "content": bounded}
                    )
                    events.append({"kind": "tool_call", "turn": turn, "tool": name})
                _shrink_conversation(messages, self.bounds.max_conversation_bytes, events)
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
            if isinstance(error, ValueError):
                cause = str(error)
            elif isinstance(error, ContainerStartError):
                cause = "container_start"
                if error.cleanup_failed:
                    events.append({"kind": "cleanup_failed", "cause": "container_cleanup"})
            elif isinstance(error, RuntimeError) and str(error) == "tool_timeout":
                cause = "tool_timeout"
            elif isinstance(error, httpx.HTTPError):
                cause = "transport_failure"
            else:
                cause = "sandbox_failure"
            events.append({"kind": "stopped", "cause": cause, "requests": requests})
            raise AgentLoopError(cause, trajectory) from error
        finally:
            cleanup_cause: str | None = None
            if sandbox is not None and not any(
                event.get("kind") == "cgroup_peaks" for event in events
            ):
                try:
                    peaks = sandbox.capture_workspace()
                    if peaks:
                        events.append({"kind": "cgroup_peaks", **peaks})
                except (RuntimeError, OSError, subprocess.SubprocessError):
                    events.append({"kind": "peak_observation_failed"})
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
                raise AgentLoopError(cleanup_cause, trajectory)
