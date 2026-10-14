from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx
import pytest
from assay_pier_bridge.agent_loop import (
    AgentLoopError,
    DockerToolSandbox,
    LoopBounds,
    RepositoryAgentClient,
)
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
        self.created.append(self)

    def execute(self, argv: list[str], *, input_text: str | None = None) -> str:
        if argv[0] == "cat":
            return (self.workspace / Path(argv[-1]).name).read_text()
        if argv[0] == "python":
            (self.workspace / argv[-1]).write_text(input_text or "")
            return "written"
        return "x" * 100

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_sandboxes() -> Iterator[None]:
    FakeSandbox.created.clear()
    yield


def _client(tmp_path: Path, handler: Any, **kwargs: Any) -> RepositoryAgentClient:
    return RepositoryAgentClient(
        api_key="test",
        image="locked-image",
        runs_root=tmp_path,
        transport=httpx.MockTransport(handler),
        sandbox_factory=FakeSandbox,
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
