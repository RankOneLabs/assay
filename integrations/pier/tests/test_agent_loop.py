from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from assay_pier_bridge.agent_loop import (
    AgentLoopError,
    ContainerStartError,
    DockerToolSandbox,
    LoopBounds,
    QuotaCellStorage,
    RepositoryAgentClient,
    ToolOutput,
)
from assay_pier_bridge.protocol import ModelRoute
from assay_pier_bridge.provider import MODEL, PROVIDER_NAME


def _answer(name: str, arguments: dict[str, str], turn: int) -> dict[str, Any]:
    return {
        "model": MODEL,
        "provider": PROVIDER_NAME,
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": f"call-{turn}",
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps(arguments)},
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001},
    }


class FakeSandbox:
    created: list[FakeSandbox] = []

    def __init__(self, workspace: Path, cache: Path, image: str) -> None:
        self.workspace = workspace
        self.cache = cache
        self.name = f"container-{len(self.created)}"
        self.closed = False
        self.visible_files = {p.relative_to(workspace).as_posix() for p in workspace.rglob("*")}
        self.modes = {
            p.relative_to(workspace).as_posix(): p.stat().st_mode & 0o777
            for p in workspace.rglob("*")
        }
        self.workspace_mode = workspace.stat().st_mode & 0o777
        self.cache_mode = cache.stat().st_mode & 0o777
        self.created.append(self)

    def execute(
        self, argv: list[str], *, max_output_bytes: int, input_text: str | None = None
    ) -> ToolOutput:
        if argv[0] == "cat":
            output = (self.workspace / Path(argv[-1]).name).read_text()
        elif argv[0] == "python":
            (self.workspace / argv[-1]).write_text(input_text or "")
            output = "written"
        else:
            output = "x" * 100
        return ToolOutput(output, len(output.encode()), False)

    def close(self) -> None:
        self.closed = True


class FakeStorage:
    def __init__(self, cell_root: Path, max_storage_mb: int) -> None:
        self.workspace = cell_root / "quota" / "workspace"
        self.cache = cell_root / "quota" / "cache"
        self.mounted = False

    def prepare(self) -> None:
        self.workspace.mkdir(parents=True)
        self.cache.mkdir()

    def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _reset_sandboxes() -> Iterator[None]:
    FakeSandbox.created.clear()
    yield


def _client(tmp_path: Path, handler: Any, **kwargs: Any) -> RepositoryAgentClient:
    storage_factory = kwargs.pop("storage_factory", FakeStorage)
    sandbox_factory = kwargs.pop("sandbox_factory", FakeSandbox)
    return RepositoryAgentClient(
        api_key="test",
        image="locked-image",
        runs_root=tmp_path,
        transport=httpx.MockTransport(handler),
        sandbox_factory=sandbox_factory,
        storage_factory=storage_factory,
        **kwargs,
    )


def test_multiple_turns_and_two_cells_are_isolated(tmp_path: Path) -> None:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        assert {tool["function"]["name"] for tool in body["tools"]} == {
            "read_file",
            "write_file",
            "run_command",
            "submit_output",
        }
        assert body["provider"]["allow_fallbacks"] is False
        if len(body["messages"]) == 2:
            return httpx.Response(200, json=_answer("read_file", {"path": "a.txt"}, len(requests)))
        return httpx.Response(200, json=_answer("submit_output", {"source": "done"}, len(requests)))

    client = _client(tmp_path, handler)
    package = {"instruction.md": "Edit", "workspace/a.txt": "one"}
    first = client.run_cell(cell_id="s:a:w0", package=package)
    second = client.run_cell(cell_id="s:b:w0", package=package)
    assert first.requests == second.requests == 2
    assert len(requests) == 4
    assert requests[2]["messages"] == requests[0]["messages"]
    left, right = FakeSandbox.created
    assert left.workspace != right.workspace
    assert left.cache != right.cache
    assert left.name != right.name
    assert left.workspace.name == right.workspace.name == "workspace"
    assert left.closed and right.closed
    assert not left.workspace.exists() and not right.workspace.exists()
    with pytest.raises(AgentLoopError, match="attempt_limit"):
        client.run_cell(cell_id="s:a:w0", package=package)


def test_local_smithers_route_runs_two_requests_without_paid_url(tmp_path: Path) -> None:
    posts: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host in {"willie", "mcbain"}
        assert "Authorization" not in request.headers
        if request.method == "POST":
            posts.append(request)
            submitted = json.loads(request.content)
            assert submitted["max_retries"] == 0
            assert submitted["model"] == "qwen-coder-32b"
            return httpx.Response(200, json={"job_id": f"job-{len(posts)}"})
        turn = len(posts)
        if request.url.host == "mcbain":
            return httpx.Response(200, json={
                "job_id": f"job-{turn}", "status": "complete",
                "usage": {"input_tokens": 10, "output_tokens": 5},
            })
        answer = (
            _answer("read_file", {"path": "a.txt"}, turn)
            if turn == 1 else _answer("submit_output", {"source": "done"}, turn)
        )
        return httpx.Response(200, json={
            "job_id": f"job-{turn}", "status": "complete", "model": "qwen-coder-32b",
            "machine": "mcbain", "result": {
                "content": None, "tool_calls": answer["choices"][0]["message"]["tool_calls"],
            },
            "created_at": "2026-10-14T10:00:00", "started_at": "2026-10-14T10:00:01",
            "completed_at": "2026-10-14T10:00:02",
        })

    client = RepositoryAgentClient(
        api_key=None, image="locked-image", runs_root=tmp_path,
        model_route=ModelRoute(
            endpoint="http://willie:8900", model="qwen-coder-32b", provider="smithers-local"
        ),
        transport=httpx.MockTransport(handler),
        sandbox_factory=FakeSandbox, storage_factory=FakeStorage,
    )
    assert client.model_route.paid_route_reachable is False
    result = client.run_cell(
        cell_id="s:a:w0", package={"instruction.md": "Edit", "workspace/a.txt": "one"}
    )
    assert result.requests == 2 and len(posts) == 2
    assert result.cost_usd is None
    model_events = [
        event for event in result.trajectory["events"] if event["kind"] == "model_request"
    ]
    assert len(model_events) == 2
    assert all(event["billing"] == "uncertain" for event in model_events)


def test_hidden_test_package_entries_never_reach_tools(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_answer("submit_output", {"source": ""}, 1))

    client = _client(tmp_path, handler)
    client.run_cell(
        cell_id="s:a:w0",
        package={
            "instruction.md": "Edit",
            "workspace/a.txt": "public",
            "hidden_tests/secret.txt": "private-marker",
        },
    )
    assert FakeSandbox.created[0].visible_files == {"a.txt"}
    assert not any(tmp_path.rglob("secret.txt"))
    with pytest.raises(AgentLoopError, match="forbidden_repository_content"):
        client.run_cell(
            cell_id="s:b:w0",
            package={"instruction.md": "Edit", "workspace/hidden_tests/secret.txt": "private"},
        )


def test_tool_and_conversation_truncation_are_recorded(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 5:
            return httpx.Response(200, json=_answer("run_command", {"command": "echo x"}, calls))
        return httpx.Response(200, json=_answer("submit_output", {"source": "ok"}, calls))

    bounds = LoopBounds(max_conversation_bytes=650, max_tool_output_bytes=20)
    result = _client(tmp_path, handler, bounds=bounds).run_cell(
        cell_id="s:a:w0", package={"instruction.md": "Edit"}
    )
    kinds = [event["kind"] for event in result.trajectory["events"]]
    assert "tool_output_truncated" in kinds
    assert "conversation_truncated" in kinds
    assert result.requests == 5


def test_repository_write_is_returned_as_patch(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200, json=_answer("write_file", {"path": "a.txt", "content": "changed"}, calls)
            )
        return httpx.Response(200, json=_answer("submit_output", {"source": ""}, calls))

    result = _client(tmp_path, handler).run_cell(
        cell_id="s:a:w0",
        package={"instruction.md": "Edit", "workspace/a.txt": "original"},
    )
    assert b"+changed" in result.patch


def test_container_uid_can_write_materialized_repository_and_cache(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_answer("submit_output", {"source": "done"}, 1))

    _client(tmp_path, handler).run_cell(
        cell_id="s:a:w0",
        package={"instruction.md": "Edit", "workspace/sub/a.txt": "original"},
    )
    sandbox = FakeSandbox.created[0]
    assert sandbox.workspace_mode == sandbox.cache_mode == 0o777
    assert sandbox.modes == {"sub": 0o777, "sub/a.txt": 0o666}


def test_bridge_loop_bounds_match_dedicated_config() -> None:
    configuration = Path(__file__).resolve().parents[1] / "config/workflow_edit.yaml"
    values = {
        key: int(value)
        for line in configuration.read_text().splitlines()
        if line and not line.startswith("#")
        for key, value in [line.split(": ", 1)]
    }
    assert {key: values[key] for key in asdict(LoopBounds())} == asdict(LoopBounds())
    assert {
        key: values[key] for key in ("attempts", "concurrency", "provider_retries", "sdk_retries")
    } == {
        "attempts": 1,
        "concurrency": 1,
        "provider_retries": 0,
        "sdk_retries": 0,
    }


def test_twenty_turn_limit_and_zero_retries(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_answer("run_command", {"command": "true"}, calls))

    client = _client(tmp_path, handler)
    assert client.resolved_config.provider_retries == 0
    assert client.resolved_config.sdk_retries == 0
    assert client.resolved_config.transport_retries == 0
    with pytest.raises(AgentLoopError) as failure:
        client.run_cell(cell_id="s:a:w0", package={"instruction.md": "Edit"})
    assert failure.value.cause == "turn_limit"
    assert calls == 20


def test_resolved_config_observes_constructed_transport_retries(tmp_path: Path) -> None:
    client = RepositoryAgentClient(
        api_key="test",
        image="locked-image",
        runs_root=tmp_path,
        transport=httpx.HTTPTransport(retries=2, trust_env=False),
        sandbox_factory=FakeSandbox,
        storage_factory=FakeStorage,
    )
    assert client.resolved_config.transport_retries == 2
    with pytest.raises(AgentLoopError, match="retry_config_violation") as failure:
        client.run_cell(cell_id="s:a:w0", package={"instruction.md": "Edit"})
    assert failure.value.trajectory["config"]["transport_retries"] == 2
    assert failure.value.trajectory["events"][-1]["requests"] == 1


@pytest.mark.parametrize(
    ("bounds", "cause"),
    [
        (LoopBounds(max_conversation_bytes=1), "conversation_limit"),
        (LoopBounds(max_request_bytes=1), "request_limit"),
        (LoopBounds(max_response_bytes=1), "response_limit"),
    ],
)
def test_byte_bounds_end_with_named_causes(tmp_path: Path, bounds: LoopBounds, cause: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_answer("submit_output", {"source": "ok"}, 1))

    client = _client(tmp_path, handler, bounds=bounds)
    with pytest.raises(AgentLoopError) as failure:
        client.run_cell(cell_id="s:a:w0", package={"instruction.md": "Edit"})
    assert failure.value.cause == cause
    assert failure.value.trajectory["events"][-1]["cause"] == cause


def test_transport_failure_consumes_attempt_without_retry(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("offline", request=request)

    client = _client(tmp_path, handler)
    with pytest.raises(AgentLoopError) as failure:
        client.run_cell(cell_id="s:a:w0", package={"instruction.md": "Edit"})
    assert failure.value.cause == "transport_failure"
    assert calls == 1


def test_docker_sandbox_mounts_only_neutral_cell_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: Any) -> Any:
        commands.append(command)
        return type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

    monkeypatch.setattr("assay_pier_bridge.agent_loop.subprocess.run", fake_run)
    workspace, cache = tmp_path / "workspace", tmp_path / "cache"
    sandbox = DockerToolSandbox(workspace, cache, "locked-image")
    sandbox.close()
    command = commands[0]
    assert command[:3] == ["docker", "run", "-d"]
    assert command[command.index("--network") + 1] == "none"
    assert f"{workspace}:/workspace:rw" in command
    assert f"{cache}:/cache:rw" in command
    assert "HOME=/cache" in command
    assert "XDG_CACHE_HOME=/cache" in command
    assert not any("hidden" in arg for arg in command)
    assert commands[-1][:3] == ["docker", "rm", "-f"]


def test_quota_storage_mounts_and_unmounts_one_cell_volume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("assay_pier_bridge.agent_loop.subprocess.run", fake_run)
    monkeypatch.setattr("assay_pier_bridge.agent_loop.os.geteuid", lambda: 1001)
    monkeypatch.setattr("assay_pier_bridge.agent_loop.os.path.ismount", lambda path: True)
    monkeypatch.setattr(
        "assay_pier_bridge.agent_loop.os.statvfs",
        lambda path: SimpleNamespace(f_blocks=100, f_frsize=4096),
    )
    cell_root = tmp_path / "cell"
    cell_root.mkdir()
    storage = QuotaCellStorage(cell_root, 512)
    storage.prepare()
    assert storage.mounted
    assert storage.workspace.is_dir() and storage.cache.is_dir()
    assert commands[0][:3] == ["mkfs.ext4", "-F", "-q"]
    assert commands[1][:5] == ["sudo", "-n", "mount", "-t", "ext4"]
    assert commands[2][:3] == ["sudo", "-n", "chmod"]
    storage.close()
    assert not storage.mounted
    assert commands[-1][:3] == ["sudo", "-n", "umount"]


def test_storage_setup_failure_is_named_and_keeps_sandbox_unstarted(tmp_path: Path) -> None:
    class FailingStorage(FakeStorage):
        def prepare(self) -> None:
            raise ValueError("storage_mount")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no model request expected")

    client = _client(tmp_path, handler, storage_factory=FailingStorage)
    with pytest.raises(AgentLoopError, match="storage_mount") as failure:
        client.run_cell(cell_id="s:a:w0", package={"instruction.md": "Edit"})
    assert not FakeSandbox.created
    assert failure.value.trajectory["events"][-1]["cause"] == "storage_mount"


def test_unverified_quota_fails_closed_and_unmounts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("assay_pier_bridge.agent_loop.subprocess.run", fake_run)
    monkeypatch.setattr("assay_pier_bridge.agent_loop.os.geteuid", lambda: 1001)
    monkeypatch.setattr("assay_pier_bridge.agent_loop.os.path.ismount", lambda path: False)
    cell_root = tmp_path / "cell"
    cell_root.mkdir()
    storage = QuotaCellStorage(cell_root, 512)
    with pytest.raises(ValueError, match="storage_quota_unverified"):
        storage.prepare()
    assert storage.mounted
    storage.close()
    assert not storage.mounted
    assert commands[-1][:3] == ["sudo", "-n", "umount"]


def test_failed_container_start_keeps_named_cause_and_records_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, "", "failed")

    monkeypatch.setattr("assay_pier_bridge.agent_loop.subprocess.run", fake_run)
    with pytest.raises(ContainerStartError) as start:
        DockerToolSandbox(tmp_path / "workspace", tmp_path / "cache", "locked-image")
    assert start.value.cleanup_failed

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no model request expected")

    client = _client(tmp_path, handler, sandbox_factory=DockerToolSandbox)
    with pytest.raises(AgentLoopError, match="container_start") as failure:
        client.run_cell(cell_id="s:a:w0", package={"instruction.md": "Edit"})
    assert {event["cause"] for event in failure.value.trajectory["events"] if "cause" in event} == {
        "container_start",
        "container_cleanup",
    }


def test_docker_tool_output_is_streamed_with_a_host_memory_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_popen = subprocess.Popen

    def fake_popen(command: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
        assert kwargs["stdout"] == subprocess.PIPE
        assert kwargs["stderr"] == subprocess.STDOUT
        return original_popen(
            [sys.executable, "-c", "import sys; sys.stdout.write('x' * 2000000)"], **kwargs
        )

    monkeypatch.setattr("assay_pier_bridge.agent_loop.subprocess.Popen", fake_popen)
    sandbox = DockerToolSandbox.__new__(DockerToolSandbox)
    sandbox.name = "fake-container"
    output = sandbox.execute(["cat", "/workspace/a.txt"], max_output_bytes=64)
    assert output.truncated
    assert output.original_bytes == len("exit=0\n") + 2_000_000
    assert len(output.text.encode()) <= 64
    assert output.text.startswith("exit=0\n")
