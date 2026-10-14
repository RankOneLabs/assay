"""One repository-capable agent attempt per cell.

The host owns the model connection. Only a fresh, network-disabled container
touches the cell's repository copy. No evaluator or hidden-test mount is passed
to that container. The fixed tool set is read_file, write_file, run_command,
and submit_output; each result is returned to the same cell's conversation.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx

from assay_pier_bridge.paths import materialize_under, safe_relative_path, submission_patch
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
    """Provisional: replace every size after experiments/workflow_edit/SMOKE.md (wf-12)."""

    max_turns: int = 20
    max_tool_schema_bytes: int = 16_384
    max_tool_output_bytes: int = 16_384
    max_conversation_bytes: int = 262_144
    max_request_bytes: int = 327_680
    max_response_bytes: int = 65_536
    max_output_tokens: int = 2_048


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
    cost_usd: float
    requests: int


class AgentLoopError(RuntimeError):
    """A trial ended at a named boundary; trajectory survives the failure."""

    def __init__(self, cause: str, trajectory: dict[str, Any]) -> None:
        self.cause = cause
        self.trajectory = trajectory
        super().__init__(cause)


class ToolSandbox(Protocol):
    name: str

    def execute(self, argv: list[str], *, input_text: str | None = None) -> str: ...
    def close(self) -> None: ...


class DockerToolSandbox:
    """Disposable container with only the neutral repository and cache mounts."""

    def __init__(self, workspace: Path, cache: Path, image: str) -> None:
        self.name = f"assay-agent-{uuid.uuid4().hex}"
        self._closed = False
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
            "512m",
            "--cpus",
            "1",
            "-v",
            f"{workspace}:/workspace:rw",
            "-v",
            f"{cache}:/cache:rw",
            "--workdir",
            "/workspace",
            "--entrypoint",
            "sleep",
            image,
            "infinity",
        ]
        started = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
        if started.returncode:
            self.close()
            raise RuntimeError(f"container_start:{started.returncode}")

    def execute(self, argv: list[str], *, input_text: str | None = None) -> str:
        result = subprocess.run(
            ["docker", "exec", "-i", "-w", "/workspace", self.name, *argv],
            input=input_text,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        return f"exit={result.returncode}\n{result.stdout}{result.stderr}"

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


def _relative_path(arguments: dict[str, Any]) -> str:
    path = arguments.get("path")
    if not isinstance(path, str):
        raise ValueError("path must be a string")
    return safe_relative_path(path).as_posix()


def _execute_tool(sandbox: ToolSandbox, name: str, arguments: dict[str, Any]) -> str:
    if name == "read_file" and set(arguments) == {"path"}:
        return sandbox.execute(["cat", "--", f"/workspace/{_relative_path(arguments)}"])
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
            ["python", "-c", script, _relative_path(arguments)], input_text=content
        )
    if name == "run_command" and set(arguments) == {"command"}:
        command = arguments["command"]
        if not isinstance(command, str) or len(command.encode("utf-8")) > 8_192:
            raise ValueError("command must be a string of at most 8192 bytes")
        return sandbox.execute(["sh", "-lc", command])
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

    api_key: str
    image: str
    runs_root: Path
    bounds: LoopBounds = field(default_factory=LoopBounds)
    transport: httpx.BaseTransport | None = None
    sandbox_factory: SandboxFactory = DockerToolSandbox
    _used_cells: set[str] = field(default_factory=set, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def __post_init__(self) -> None:
        if not self.api_key or any(char.isspace() for char in self.api_key):
            raise ValueError("nonblank API key required")
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
        workspace, baseline, cache = (
            cell_root / "workspace",
            cell_root / "baseline",
            cell_root / "cache",
        )
        for directory in (workspace, baseline, cache):
            directory.mkdir(parents=True, exist_ok=False)
        sandbox: ToolSandbox | None = None
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": instruction},
        ]
        prompt_tokens = completion_tokens = requests = 0
        cost_usd = 0.0
        try:
            materialize_under(workspace, repository)
            materialize_under(baseline, repository)
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
                if (
                    isinstance(cost, bool)
                    or not isinstance(cost, (int, float))
                    or not math.isfinite(cost)
                    or cost < 0
                ):
                    raise ValueError("provider_usage")
                if usage["completion_tokens"] > self.bounds.max_output_tokens:
                    raise ValueError("output_token_limit")
                prompt_tokens += usage["prompt_tokens"]
                completion_tokens += usage["completion_tokens"]
                cost_usd += cost
                calls = message.get("tool_calls")
                if (
                    choice.get("finish_reason") != "tool_calls"
                    or not isinstance(calls, list)
                    or not calls
                ):
                    raise ValueError("no_tool_call")
                messages.append(message)
                for call in calls:
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
                            or len(calls) != 1
                        ):
                            raise ValueError("invalid_submission")
                        _shrink_conversation(messages, self.bounds.max_conversation_bytes, events)
                        if len(_json_bytes(messages)) > self.bounds.max_conversation_bytes:
                            raise ValueError("conversation_limit")
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
                        output = _execute_tool(sandbox, name, arguments)
                    except ValueError as error:
                        raise ValueError("invalid_tool_call") from error
                    bounded, truncated = _bounded_text(output, self.bounds.max_tool_output_bytes)
                    if truncated:
                        events.append(
                            {
                                "kind": "tool_output_truncated",
                                "turn": turn,
                                "tool": name,
                                "original_bytes": len(output.encode("utf-8")),
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
            trajectory["messages"] = messages
            if isinstance(error, ValueError):
                cause = str(error)
            elif isinstance(error, RuntimeError) and str(error).startswith("container_start:"):
                cause = "container_start"
            elif isinstance(error, httpx.HTTPError):
                cause = "transport_failure"
            else:
                cause = "sandbox_failure"
            events.append({"kind": "stopped", "cause": cause, "requests": requests})
            raise AgentLoopError(cause, trajectory) from error
        finally:
            try:
                if sandbox is not None:
                    sandbox.close()
            except (RuntimeError, OSError, subprocess.SubprocessError) as error:
                events.append({"kind": "stopped", "cause": "container_cleanup"})
                raise AgentLoopError("container_cleanup", trajectory) from error
            finally:
                shutil.rmtree(cell_root, ignore_errors=True)
