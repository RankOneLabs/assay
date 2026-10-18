from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tarfile
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any

import assay_pier_bridge.agent_loop as agent_loop
import httpx
import pytest
from assay_pier_bridge.agent_loop import (
    CANDIDATE_STOP_CAUSES,
    HAIKU_TURN_ROUTE,
    PILOT_TOOLS_REVIEW,
    PILOT_TOOLS_T1,
    SYSTEM_PROMPT,
    TOOLS,
    AgentLoopError,
    ContainerStartError,
    ConversationLimitError,
    DockerToolSandbox,
    LoopBounds,
    ModelDispatchError,
    ModelTurn,
    QuotaCellStorage,
    RepositoryAgentClient,
    SandboxLimits,
    ToolOutput,
    _shrink_conversation,
    _submission,
)
from assay_pier_bridge.paths import ArtifactCollectionRejected, extract_workspace_archive
from assay_pier_bridge.protocol import ModelRoute
from assay_pier_bridge.provider import MODEL, PROVIDER_NAME

LOCAL = ModelRoute(endpoint="http://willie:8900", model="qwen-coder-32b", provider="smithers-local")


def _call(name: str, arguments: dict[str, Any], turn: int) -> dict[str, Any]:
    return {
        "id": f"call-{turn}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def _answer(name: str, arguments: dict[str, str], turn: int) -> dict[str, Any]:
    return {
        "model": MODEL,
        "provider": PROVIDER_NAME,
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {"role": "assistant", "tool_calls": [_call(name, arguments, turn)]},
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001},
    }


def test_haiku_turn_request_body_is_byte_identical(tmp_path: Path) -> None:
    messages = [{"role": "user", "content": "hello"}]
    captured: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.content)
        return httpx.Response(200, json=_answer("submit_output", {"summary": "done"}, 1))

    client = _client(tmp_path, handler)
    client._openrouter_turn(messages, HAIKU_TURN_ROUTE)
    # Literal copy of the body before route parameterization, including key order.
    prior_body = {
        "model": MODEL,
        "messages": messages,
        "tools": client.tools,
        "tool_choice": "auto",
        "max_tokens": client.bounds.max_output_tokens,
        "stream": False,
        "provider": {
            "data_collection": "deny",
            "zdr": True,
            "only": ["amazon-bedrock"],
            "order": ["amazon-bedrock"],
            "allow_fallbacks": False,
            "require_parameters": True,
            "max_price": {"prompt": 0.25, "completion": 1.25, "request": 0},
        },
    }
    assert captured == [
        json.dumps(prior_body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ]


def test_paid_turn_uses_the_current_pilot_tool_schema(tmp_path: Path) -> None:
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=_answer("submit_output", {"summary": "done"}, 1))

    _client(tmp_path, handler)._turn(
        [{"role": "user", "content": "Review"}], 1, None, PILOT_TOOLS_REVIEW
    )
    assert captured[0]["tools"] == PILOT_TOOLS_REVIEW


def test_paid_turn_forwards_deadline_to_openrouter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, lambda request: httpx.Response(500))
    seen: list[float | None] = []

    def fake_openrouter(*args: Any, deadline: float | None = None,
                        on_dispatch: Any = None) -> ModelTurn:
        seen.append(deadline)
        return ModelTurn(message={}, finish_reason="stop", prompt_tokens=0,
                         completion_tokens=0, cost_usd=0.0)

    monkeypatch.setattr(client, "_openrouter_turn", fake_openrouter)
    deadline = time.monotonic() + 20
    client._turn([], 1, deadline, TOOLS)
    assert seen == [deadline]


def test_haiku_turn_uses_caller_loop_bounds(tmp_path: Path) -> None:
    captured: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.content)
        return httpx.Response(200, json=_answer("submit_output", {"summary": "done"}, 1))

    bounds = replace(
        LoopBounds(), max_request_bytes=120_000, max_conversation_bytes=110_000,
        max_output_tokens=9_000,
    )
    client = _client(tmp_path, handler, bounds=bounds)
    client._openrouter_turn([{"role": "user", "content": "x" * 99_000}], HAIKU_TURN_ROUTE)
    assert len(captured) == 1
    assert len(captured[0]) > 98_304
    assert json.loads(captured[0])["max_tokens"] == 9_000


def test_turn_uses_route_limits_and_identity(tmp_path: Path) -> None:
    route = replace(
        HAIKU_TURN_ROUTE,
        model="example/test",
        provider="example",
        provider_name="Example",
        max_prompt_price_per_million=2,
        max_completion_price_per_million=10,
        max_output_tokens=128,
        tool_choice="forced",
    )
    dispatched = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal dispatched
        dispatched += 1
        body = json.loads(request.content)
        assert body["model"] == route.model
        assert body["provider"]["only"] == [route.provider]
        assert body["provider"]["max_price"] == {
            "prompt": 2,
            "completion": 10,
            "request": 0,
        }
        assert body["max_tokens"] == 128
        assert body["tool_choice"] == {
            "type": "function",
            "function": {"name": "submit_output"},
        }
        return httpx.Response(200, json={**_answer("submit_output", {"summary": "done"}, 1),
                                         "model": route.model, "provider": route.provider_name})

    client = _client(tmp_path, handler)
    assert client._openrouter_turn([{"role": "user", "content": "hello"}], route).cost_usd == 0.001
    assert dispatched == 1

    for mismatch in ("model", "provider"):
        def wrong_identity(request: httpx.Request, field: str = mismatch) -> httpx.Response:
            response = _answer("submit_output", {"summary": "done"}, 1)
            response.update(model=route.model, provider=route.provider_name)
            response[field] = "wrong"
            return httpx.Response(200, json=response)

        with pytest.raises(ValueError, match="provider_identity"):
            _client(tmp_path, wrong_identity)._openrouter_turn(
                [{"role": "user", "content": "hello"}], route
            )

    too_small = replace(route, max_request_body_bytes=1)
    with pytest.raises(ValueError, match="request_limit"):
        client._openrouter_turn([{"role": "user", "content": "hello"}], too_small)
    assert dispatched == 1


class FakeSandbox:
    created: list[FakeSandbox] = []
    peaks: dict[str, int] = {}
    # ``oom`` is killed inside its own tool call; ``oom-later`` leaves a process
    # behind that is killed after the tool result was observed.
    oom_kill_count = 0
    late_oom_kills = 0

    def __init__(self, workspace: Path, cache: Path, image: str, cell_id: str) -> None:
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
        self.timeouts: list[float] = []
        self.created.append(self)

    def execute(
        self,
        argv: list[str],
        *,
        max_output_bytes: int,
        input_text: str | None = None,
        timeout_s: float = 120.0,
    ) -> ToolOutput:
        self.timeouts.append(timeout_s)
        if argv[-1] == "hang":
            raise RuntimeError("tool_timeout")
        if argv[-1] == "oom":
            type(self).oom_kill_count += 1
            return ToolOutput("exit=137\nKilled\n", 14, False)
        if argv[-1] == "oom-later":
            type(self).late_oom_kills += 1
        if argv[0] == "python":
            # The real in-container tool scripts, run against this cell's tree.
            script = argv[2].replace("'/workspace'", repr(str(self.workspace)))
            ran = subprocess.run(
                [sys.executable, "-c", script, *argv[3:]],
                input=(input_text or "").encode("utf-8"), capture_output=True, check=False,
            )
            output = f"exit={ran.returncode}\n" + (ran.stdout + ran.stderr).decode("utf-8")
        else:
            output = "exit=0\n" + "x" * 100
        encoded = output.encode("utf-8")
        return ToolOutput(
            encoded[:max_output_bytes].decode("utf-8", errors="ignore"),
            len(encoded),
            len(encoded) > max_output_bytes,
        )

    def close(self) -> None:
        self.closed = True

    def interrupt(self) -> None:
        self.interrupted = True

    def capture_workspace(self) -> dict[str, int]:
        if not self.peaks:
            return {}
        total = self.peaks.get("oom_kills", 0) + self.oom_kill_count + self.late_oom_kills
        return {**self.peaks, "oom_kills": total}

    def oom_kills(self) -> int | None:
        return self.peaks.get("oom_kills", 0) + self.oom_kill_count if self.peaks else None


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
    FakeSandbox.peaks = {}
    FakeSandbox.oom_kill_count = FakeSandbox.late_oom_kills = 0
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


class Scripted:
    """A local-route turn completion that replays fixed tool calls."""

    def __init__(
        self,
        *turns: list[dict[str, Any]],
        finish: str = "tool_calls",
        content: str | None = None,
        completion_tokens: int = 3,
    ) -> None:
        self.turns = list(turns)
        self.finish = finish
        self.content = content
        self.completion_tokens = completion_tokens
        self.seen: list[dict[str, Any]] = []
        self.tool_schemas: list[list[dict[str, Any]]] = []

    def __call__(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
        turn: int,
        deadline: float | None,
    ) -> ModelTurn:
        self.seen.append({"messages": json.loads(json.dumps(messages)), "turn": turn})
        self.tool_schemas.append(json.loads(json.dumps(tools)))
        calls = self.turns[turn - 1] if turn <= len(self.turns) else self.turns[-1]
        return ModelTurn(
            message={"role": "assistant", "content": self.content, "tool_calls": calls},
            finish_reason=self.finish,
            prompt_tokens=7,
            completion_tokens=self.completion_tokens,
            cost_usd=None,
            observations={"smithers_job_id": f"job-{turn}"},
        )


def _local(tmp_path: Path, completion: Any, **kwargs: Any) -> RepositoryAgentClient:
    return RepositoryAgentClient(
        api_key=None,
        image="locked-image",
        runs_root=tmp_path,
        model_route=LOCAL,
        completion=completion,
        sandbox_factory=kwargs.pop("sandbox_factory", FakeSandbox),
        storage_factory=kwargs.pop("storage_factory", FakeStorage),
        **kwargs,
    )


def _pilot(tmp_path: Path, completion: Any, **kwargs: Any) -> RepositoryAgentClient:
    return _local(
        tmp_path, completion, pilot_mode=True,
        next_user_turns=("Review your first submission", "Check the remaining v1 work"),
        writable_prefixes=("src/", "tests/"),
        max_tool_calls_per_turn=15, max_tool_calls_per_cell=40, **kwargs,
    )


def test_default_tools_are_independent_of_other_clients(tmp_path: Path) -> None:
    first = _local(tmp_path, Scripted())
    second = _local(tmp_path, Scripted())
    assert first.tools == second.tools == TOOLS

    first.tools[0]["function"]["name"] = "changed"
    assert second.tools == TOOLS


def test_pilot_three_submissions_share_workspace_and_capture_each_diff(tmp_path: Path) -> None:
    completion = Scripted(
        [_call("write_file", {"path": "src/a.ts", "content": "first\n"}, 1)],
        [_call("submit_output", {"title": "First", "body": "Changed a"}, 2)],
        [_call("replace_in_file", {"path": "src/a.ts", "old": "first", "new": "second"}, 3)],
        [_call("submit_output", {"verdict": "incomplete", "remaining_v1": "check a",
                                  "checks_performed": "read"}, 4)],
        [_call("read_file", {"path": "src/a.ts", "start_line": 1, "end_line": 1}, 5)],
        [_call("submit_output", {"verdict": "complete", "remaining_v1": "",
                                  "checks_performed": "read and test"}, 6)],
    )
    result = _pilot(tmp_path, completion).run_cell(
        cell_id="s:a:w0", package={"instruction.md": "Edit", "workspace/src/a.ts": "original\n"}
    )
    assert len(FakeSandbox.created) == 1
    turns = result.trajectory["turns"]
    assert [item["turn"] for item in turns] == ["T1", "T2", "T3"]
    assert [item["submission"] for item in turns] == [
        {"title": "First", "body": "Changed a"},
        {"verdict": "incomplete", "remaining_v1": "check a", "checks_performed": "read"},
        {"verdict": "complete", "remaining_v1": "", "checks_performed": "read and test"},
    ]
    assert b"+second" in result.patch and result.files["src/a.ts"] == b"second\n"
    assert "+first" in turns[0]["workspace_diff"]
    assert "+second" in turns[1]["workspace_diff"]
    assert turns[2]["workspace_diff"] == turns[1]["workspace_diff"]
    assert completion.seen[2]["messages"][-1]["content"] == "Review your first submission"
    assert completion.seen[4]["messages"][-1]["content"] == "Check the remaining v1 work"
    assert completion.tool_schemas[0] == PILOT_TOOLS_T1
    assert completion.tool_schemas[2] == PILOT_TOOLS_REVIEW
    assert turns[2]["tool_calls"][0]["returned_range"] == {
        "path": "src/a.ts", "start_line": 1, "end_line": 1, "complete": True,
    }
    assert turns[2]["usage"]["requests"] == 2


def test_failed_pilot_dispatch_counts_in_turn_usage(tmp_path: Path) -> None:
    def failing(**kwargs: Any) -> ModelTurn:
        raise ModelDispatchError("Unavailable", "failed before a response")

    with pytest.raises(AgentLoopError) as failure:
        _pilot(tmp_path, failing).run_cell(
            cell_id="s:a:w0", package={"instruction.md": "Edit"}
        )
    assert failure.value.usage["requests"] == 1
    assert failure.value.trajectory["turns"][0]["usage"]["requests"] == 1


def test_stopped_later_turn_recaptures_tmpfs_workspace(tmp_path: Path) -> None:
    class StagedSandbox(FakeSandbox):
        def __init__(self, workspace: Path, cache: Path, image: str, cell_id: str) -> None:
            super().__init__(workspace, cache, image, cell_id)
            self.host_workspace = workspace
            self.workspace = workspace.parent / "container_workspace"
            shutil.copytree(workspace, self.workspace)

        def capture_workspace(self) -> dict[str, int]:
            shutil.rmtree(self.host_workspace)
            shutil.copytree(self.workspace, self.host_workspace)
            return {}

    completion = Scripted(
        [_call("write_file", {"path": "src/a.ts", "content": "first\n"}, 1)],
        [_call("submit_output", {"title": "First", "body": "Done"}, 2)],
        [_call("write_file", {"path": "src/a.ts", "content": "second\n"}, 3)],
        [],
    )
    with pytest.raises(AgentLoopError) as failure:
        _pilot(tmp_path, completion, sandbox_factory=StagedSandbox).run_cell(
            cell_id="s:a:w0",
            package={"instruction.md": "Edit", "workspace/src/a.ts": "original\n"},
        )
    assert failure.value.cause == "no_tool_call"
    assert "+second" in failure.value.trajectory["turns"][1]["workspace_diff"]
    assert b"+second" in failure.value.evidence["candidate.patch"]


def test_pilot_submit_shapes_reject_summary_and_invalid_verdict() -> None:
    with pytest.raises(ValueError, match="requires"):
        _submission({"summary": "old"}, 1, True)
    assert _submission({"title": "A", "body": "B"}, 1, True)["title"] == "A"
    review = {"verdict": "unsure", "remaining_v1": "more", "checks_performed": "test"}
    assert _submission(review, 2, True) == review
    with pytest.raises(ValueError, match="verdict"):
        _submission({**review, "verdict": "yes"}, 3, True)


def test_pilot_rejects_old_submit_call_in_the_running_turn(tmp_path: Path) -> None:
    completion = Scripted(
        [_call("submit_output", {"summary": "old"}, 1)],
        [_call("submit_output", {"title": "A", "body": "B"}, 2)],
        [_call("submit_output", {"verdict": "unsure", "remaining_v1": "x",
                                  "checks_performed": "read"}, 3)],
        [_call("submit_output", {"verdict": "complete", "remaining_v1": "",
                                  "checks_performed": "test"}, 4)],
    )
    result = _pilot(tmp_path, completion).run_cell(
        cell_id="s:a:w0", package={"instruction.md": "Edit"}
    )
    assert result.trajectory["turns"][0]["tool_calls"][0]["returned_text"].startswith(
        "error: submit_output requires"
    )
    assert result.trajectory["turns"][0]["submission"] == {"title": "A", "body": "B"}


def test_pilot_search_scope_is_structural_in_trace(tmp_path: Path) -> None:
    completion = Scripted(
        [_call("search_files", {"scope": "src", "query": "needle"}, 1)],
        [_call("submit_output", {"title": "A", "body": "B"}, 2)],
        [_call("submit_output", {"verdict": "unsure", "remaining_v1": "x",
                                  "checks_performed": "searched"}, 3)],
        [_call("submit_output", {"verdict": "complete", "remaining_v1": "",
                                  "checks_performed": "searched"}, 4)],
    )
    result = _pilot(tmp_path, completion).run_cell(
        cell_id="s:a:w0", package={"instruction.md": "Search", "workspace/src/a.ts": "needle\n"}
    )
    search = result.trajectory["turns"][0]["tool_calls"][0]
    assert search["arguments"] == {"scope": "src", "query": "needle"}
    assert "src/a.ts:1:needle" in search["returned_text"]
    assert search["exit_code"] == 0


def test_pilot_mode_neither_defines_nor_swaps_in_a_system_prompt(tmp_path: Path) -> None:
    """G14: the experiment owns its prompt text, so the bridge must not carry one.

    The deleted swap-in fired precisely when a pilot caller passed the non-pilot
    ``SYSTEM_PROMPT``, which is why that is the prompt this guard passes in.
    """
    assert not hasattr(agent_loop, "PILOT_SYSTEM_PROMPT")
    client = _pilot(tmp_path, Scripted(), system_prompt=SYSTEM_PROMPT)
    assert client.system_prompt == SYSTEM_PROMPT


def test_pilot_turn_tool_call_cap_ends_only_that_turn(tmp_path: Path) -> None:
    calls = [_call("run_command", {"command": "true"}, number) for number in range(16)]
    completion = Scripted(
        calls,
        [_call("submit_output", {"verdict": "unsure", "remaining_v1": "x",
                                  "checks_performed": "read"}, 17)],
        [_call("submit_output", {"verdict": "complete", "remaining_v1": "",
                                  "checks_performed": "test"}, 18)],
    )
    capped = _pilot(tmp_path, completion).run_cell(
        cell_id="s:a:w0", package={"instruction.md": "Work"}
    )
    first = capped.trajectory["turns"][0]
    assert first["stop_cause"] == "turn_tool_call_limit"
    assert first["submission"] is None
    assert len(first["tool_calls"]) == 15
    assert first["patch_ref"].startswith("sha256:")
    assert first["tree_digest"] == first["baseline_tree_digest"]
    assert capped.trajectory["turns"][1]["submission"]["verdict"] == "unsure"
    assert capped.summary == ""
    assert completion.seen[1]["messages"][-1]["content"] == "Review your first submission"


def test_pilot_cell_tool_call_cap_ends_the_cell(tmp_path: Path) -> None:
    def commands(count: int, start: int) -> list[dict[str, Any]]:
        return [_call("run_command", {"command": "true"}, number)
                for number in range(start, start + count)]

    completion = Scripted(
        [*commands(14, 0), _call("submit_output", {"title": "A", "body": "B"}, 14)],
        [*commands(14, 15), _call("submit_output", {
            "verdict": "unsure", "remaining_v1": "x", "checks_performed": "test"}, 29)],
        [*commands(10, 30), _call("submit_output", {
            "verdict": "complete", "remaining_v1": "", "checks_performed": "test"}, 40)],
    )
    with pytest.raises(AgentLoopError) as per_cell:
        _pilot(tmp_path, completion).run_cell(
            cell_id="s:b:w0", package={"instruction.md": "Work"}
        )
    assert per_cell.value.cause == "cell_tool_call_limit"
    assert sum(len(turn["tool_calls"]) for turn in per_cell.value.trajectory["turns"]) == 40
    assert per_cell.value.trajectory["turns"][-1]["stop_cause"] == "cell_tool_call_limit"
    assert per_cell.value.trajectory["turns"][-1]["patch_ref"].startswith("sha256:")
    assert per_cell.value.cause in CANDIDATE_STOP_CAUSES


def test_pilot_model_turn_limit_records_cell_stop(tmp_path: Path) -> None:
    completion = Scripted([_call("run_command", {"command": "true"}, 1)])
    with pytest.raises(AgentLoopError) as failure:
        _local(
            tmp_path, completion, pilot_mode=True,
            next_user_turns=("Review", "Check"), writable_prefixes=("src/", "tests/"),
            max_tool_calls_per_turn=40, max_tool_calls_per_cell=40,
        ).run_cell(
            cell_id="s:a:w0", package={"instruction.md": "Work"}
        )
    assert failure.value.cause == "turn_limit"
    assert failure.value.trajectory["turns"][0]["stop_cause"] == "turn_limit"
    assert len(completion.seen) == 20


def test_pilot_deadline_records_distinct_cell_stop(tmp_path: Path) -> None:
    with pytest.raises(AgentLoopError) as failure:
        _pilot(tmp_path, Scripted([_call("run_command", {"command": "true"}, 1)])).run_cell(
            cell_id="s:a:w0", package={"instruction.md": "Work"},
            deadline=time.monotonic() - 1,
        )
    assert failure.value.cause == "agent_deadline"
    assert failure.value.trajectory["turns"][0]["stop_cause"] == "agent_deadline"


def test_pilot_truncated_output_and_scope_evidence(tmp_path: Path) -> None:
    completion = Scripted(
        [_call("read_file", {"path": "src/a.ts", "start_line": 1, "end_line": None}, 1)],
        [_call("write_file", {"path": "tests/new.ts", "content": "test"}, 2)],
        [_call("submit_output", {"title": "A", "body": "B"}, 3)],
        [_call("submit_output", {"verdict": "complete", "remaining_v1": "",
                                  "checks_performed": "read"}, 4)],
        [_call("submit_output", {"verdict": "complete", "remaining_v1": "",
                                  "checks_performed": "read"}, 5)],
    )
    result = _pilot(tmp_path, completion, bounds=LoopBounds(max_tool_output_bytes=100)).run_cell(
        cell_id="s:a:w0", package={"instruction.md": "Edit", "workspace/src/a.ts": "x" * 300}
    )
    read = result.trajectory["turns"][0]["tool_calls"][0]
    assert read["truncated"] is True
    assert read["returned_range"]["end_line"] < 1
    assert result.files["tests/new.ts"] == b"test"
    assert "+test" in result.trajectory["turns"][0]["workspace_diff"]

    tamper = Scripted([_call("write_file", {"path": "package.json", "content": "{}"}, 1)],
                      [_call("submit_output", {"title": "A", "body": "B"}, 2)])
    with pytest.raises(AgentLoopError) as failure:
        _pilot(tmp_path, tamper).run_cell(cell_id="s:b:w0", package={"instruction.md": "Edit"})
    assert failure.value.cause == "tampering"


@pytest.mark.parametrize(
    ("source", "cap", "truncated", "end_line"),
    [
        ("value [truncated: line 99 is just source text]\n", 1024, False, 1),
        ("x" * 300, 80, True, 0),
    ],
)
def test_pilot_read_metadata_is_separate_from_source_text(
    tmp_path: Path, source: str, cap: int, truncated: bool, end_line: int
) -> None:
    completion = Scripted(
        [_call("read_file", {"path": "src/a.ts", "start_line": 1, "end_line": None}, 1)],
        [_call("submit_output", {"title": "A", "body": "B"}, 2)],
        [_call("submit_output", {"verdict": "unsure", "remaining_v1": "",
                                  "checks_performed": "read"}, 3)],
        [_call("submit_output", {"verdict": "complete", "remaining_v1": "",
                                  "checks_performed": "read"}, 4)],
    )
    result = _pilot(tmp_path, completion, bounds=LoopBounds(max_tool_output_bytes=cap)).run_cell(
        cell_id="s:a:w0", package={"instruction.md": "Read", "workspace/src/a.ts": source}
    )
    read = result.trajectory["turns"][0]["tool_calls"][0]
    assert read["truncated"] is truncated
    assert read["returned_range"]["end_line"] == end_line
    if not truncated:
        assert read["returned_text"] == f"exit=0\n{source}"


def test_multiple_turns_and_two_cells_are_isolated(tmp_path: Path) -> None:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        assert [tool["function"]["name"] for tool in body["tools"]] == [
            "read_file",
            "write_file",
            "replace_in_file",
            "run_command",
            "submit_output",
        ]
        assert body["provider"]["allow_fallbacks"] is False
        if len(body["messages"]) == 2:
            return httpx.Response(200, json=_answer("read_file", {"path": "a.txt"}, len(requests)))
        return httpx.Response(
            200, json=_answer("submit_output", {"summary": "done"}, len(requests))
        )

    client = _client(tmp_path, handler)
    package = {"instruction.md": "Edit", "workspace/a.txt": "one"}
    first = client.run_cell(cell_id="s:a:w0", package=package)
    second = client.run_cell(cell_id="s:b:w0", package=package)
    assert first.requests == second.requests == 2
    assert first.cost_usd == pytest.approx(0.002)
    assert len(requests) == 4
    assert requests[2]["messages"] == requests[0]["messages"]
    left, right = FakeSandbox.created
    assert left.workspace != right.workspace
    assert left.name != right.name
    assert left.closed and right.closed
    assert not left.workspace.exists() and not right.workspace.exists()
    with pytest.raises(AgentLoopError, match="attempt_limit"):
        client.run_cell(cell_id="s:a:w0", package=package)


def test_custom_agent_identity_reaches_paid_request(tmp_path: Path) -> None:
    tools = [TOOLS[-1]]
    prefix = ({"role": "user", "content": "Pinned pilot session"},)
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=_answer("submit_output", {"summary": "done"}, 1))

    _client(tmp_path, handler, tools=tools, system_prompt="Pilot prompt",
            message_prefix=prefix).run_cell(
        cell_id="s:a:w0", package={"instruction.md": "Edit"}
    )
    assert bodies[0]["tools"] == tools
    assert bodies[0]["messages"] == [
        {"role": "system", "content": "Pilot prompt"},
        {"role": "user", "content": "Edit"},
        *prefix,
    ]


def test_shrink_keeps_declared_prefix_and_raises_typed_cause() -> None:
    prefix = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "pinned example"},
    ]
    exchange = [
        {"role": "assistant", "tool_calls": [{"id": "old"}]},
        {"role": "tool", "tool_call_id": "old", "content": "old result"},
        {"role": "assistant", "tool_calls": [{"id": "latest"}]},
        {"role": "tool", "tool_call_id": "latest", "content": "latest result"},
    ]
    messages = [*prefix, *exchange]
    events: list[dict[str, Any]] = []
    _shrink_conversation(messages, 290, events, prefix_length=len(prefix))
    assert messages[:len(prefix)] == prefix
    assert messages[len(prefix):] == exchange[2:]
    assert events == [{"kind": "conversation_truncated", "messages_removed": 2}]
    with pytest.raises(ConversationLimitError) as failure:
        _shrink_conversation(prefix.copy(), 1, [], prefix_length=len(prefix))
    assert failure.value.cause == "conversation_limit"


def test_pilot_session_remains_pinned_past_shrink_threshold(tmp_path: Path) -> None:
    prefix = (
        {"role": "assistant", "content": "handoff"},
        {"role": "tool", "tool_call_id": "handoff", "content": "account" * 100},
        {"role": "user", "content": "Verify the whole migration"},
    )
    completion = Scripted([_call("submit_output", {"title": "Done", "body": ""}, 1)])
    with pytest.raises(AgentLoopError) as failure:
        _pilot(
            tmp_path, completion, message_prefix=prefix,
            bounds=replace(LoopBounds(), max_conversation_bytes=100),
        ).run_cell(cell_id="s:a:w0", package={"instruction.md": "Edit"})
    assert failure.value.cause == "conversation_limit"
    assert completion.seen == []
    assert failure.value.trajectory["messages"][2:] == list(prefix)


def test_mid_cell_shrink_preserves_recorded_transcript(tmp_path: Path) -> None:
    completion = Scripted(
        [_call("run_command", {"command": "true"}, 1)],
        [_call("run_command", {"command": "true"}, 2)],
        [_call("submit_output", {"summary": "done"}, 3)],
    )
    client = _local(
        tmp_path, completion, system_prompt="S",
        bounds=replace(LoopBounds(), max_conversation_bytes=450),
    )
    result = client.run_cell(cell_id="s:a:w0", package={"instruction.md": "Edit"})
    assert any(e["kind"] == "conversation_truncated" for e in result.trajectory["events"])
    recorded = result.trajectory["messages"]
    assert [m["tool_call_id"] for m in recorded if m["role"] == "tool"] == [
        "call-1", "call-2"
    ]
    assert all(m["tool_call_id"] != "call-1" for m in completion.seen[2]["messages"]
               if m["role"] == "tool")


def test_local_route_requires_an_injected_completion_and_no_key(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="injected turn completion"):
        _local(tmp_path, None)
    with pytest.raises(ValueError, match="must not receive"):
        RepositoryAgentClient(
            api_key="key", image="i", runs_root=tmp_path, model_route=LOCAL, completion=Scripted()
        )
    with pytest.raises(ValueError, match="built in"):
        RepositoryAgentClient(api_key="key", image="i", runs_root=tmp_path, completion=Scripted())


def test_local_turns_record_observations_and_uncertain_billing(tmp_path: Path) -> None:
    completion = Scripted(
        [_call("write_file", {"path": "src/a.ts", "content": "two"}, 1)],
        [_call("submit_output", {"summary": "edited"}, 2)],
    )
    result = _local(tmp_path, completion, writable_prefixes=("src/",)).run_cell(
        cell_id="s:a:w0", package={"instruction.md": "Edit", "workspace/src/a.ts": "one"}
    )
    assert result.summary == "edited"
    assert result.cost_usd is None
    assert result.files == {"src/a.ts": b"two"}
    assert b"+two" in result.patch
    assert result.baseline_tree_digest != result.final_tree_digest
    model_events = [e for e in result.trajectory["events"] if e["kind"] == "model_request"]
    assert [e["observations"]["smithers_job_id"] for e in model_events] == ["job-1", "job-2"]
    assert all(e["billing"] == "uncertain" for e in model_events)
    # The replayed assistant turn carries exactly the portable tool-call fields.
    replayed = completion.seen[1]["messages"][2]
    assert replayed["tool_calls"][0].keys() == {"id", "type", "function"}


def test_observations_cannot_replace_model_event_fields(tmp_path: Path) -> None:
    def completion(**kwargs: Any) -> ModelTurn:
        return ModelTurn(
            message={
                "role": "assistant", "tool_calls": [_call("submit_output", {"summary": "ok"}, 1)]
            },
            finish_reason="tool_calls", prompt_tokens=7, completion_tokens=3,
            cost_usd=None, observations={"kind": "forged", "prompt_tokens": 999},
        )

    result = _local(tmp_path, completion).run_cell(
        cell_id="s:a:w0", package={"instruction.md": "Edit"}
    )
    event = next(e for e in result.trajectory["events"] if e["kind"] == "model_request")
    assert event["prompt_tokens"] == 7
    assert event["observations"] == {"kind": "forged", "prompt_tokens": 999}


def test_tool_call_mistakes_go_back_to_the_model(tmp_path: Path) -> None:
    completion = Scripted(
        [
            _call("delete_everything", {"path": "x"}, 1),
            {"id": "bad-json", "type": "function",
             "function": {"name": "read_file", "arguments": "{nope"}},
            _call("read_file", {"path": "../escape"}, 1),
        ],
        [_call("submit_output", {"summary": "s"}, 2), _call("run_command", {"command": "x"}, 3)],
        [_call("submit_output", {"summary": "s"}, 4)],
    )
    result = _local(tmp_path, completion).run_cell(
        cell_id="s:a:w0", package={"instruction.md": "Edit", "workspace/a.txt": "one"}
    )
    errors = [e for e in result.trajectory["events"] if e["kind"] == "tool_error"]
    assert len(errors) == 4
    assert result.requests == 3
    tool_messages = [m for m in result.trajectory["messages"] if m["role"] == "tool"]
    assert all(m["content"].startswith("error: ") for m in tool_messages[:3])


@pytest.mark.parametrize(
    ("completion", "cause"),
    [
        (Scripted([]), "no_tool_call"),
        (Scripted([], finish="length"), "output_token_limit"),
        (Scripted([{"id": 3}]), "invalid_tool_call"),
    ],
)
def test_model_stops_are_named_and_keep_partial_work(
    tmp_path: Path, completion: Scripted, cause: str
) -> None:
    with pytest.raises(AgentLoopError) as failure:
        _local(tmp_path, completion).run_cell(
            cell_id="s:a:w0", package={"instruction.md": "Edit", "workspace/a.txt": "one"}
        )
    assert failure.value.cause == cause
    assert failure.value.usage["requests"] == 1
    assert "candidate.patch" in failure.value.evidence


def test_turn_limit_retains_what_the_model_left_behind(tmp_path: Path) -> None:
    completion = Scripted([_call("write_file", {"path": "a.txt", "content": "half"}, 1)])
    with pytest.raises(AgentLoopError) as failure:
        _local(tmp_path, completion).run_cell(
            cell_id="s:a:w0", package={"instruction.md": "Edit", "workspace/a.txt": "one"}
        )
    assert failure.value.cause == "turn_limit"
    assert failure.value.usage["requests"] == 20
    assert b"+half" in failure.value.evidence["candidate.patch"]


def test_expired_deadline_stops_before_the_next_turn(tmp_path: Path) -> None:
    completion = Scripted([_call("run_command", {"command": "true"}, 1)])
    with pytest.raises(AgentLoopError, match="agent_deadline") as failure:
        _local(tmp_path, completion).run_cell(
            cell_id="s:a:w0",
            package={"instruction.md": "Edit"},
            deadline=time.monotonic() - 1,
        )
    assert failure.value.usage["requests"] == 0


def test_tool_timeout_is_bounded_by_the_remaining_budget(tmp_path: Path) -> None:
    completion = Scripted(
        [_call("run_command", {"command": "true"}, 1)],
        [_call("submit_output", {"summary": "s"}, 2)],
    )
    _local(tmp_path, completion).run_cell(
        cell_id="s:a:w0", package={"instruction.md": "Edit"}, deadline=time.monotonic() + 30
    )
    assert 0 < FakeSandbox.created[0].timeouts[0] <= 30


def test_hung_command_is_killed_and_reported_back(tmp_path: Path) -> None:
    completion = Scripted(
        [_call("run_command", {"command": "hang"}, 1)],
        [_call("submit_output", {"summary": "s"}, 2)],
    )
    result = _local(tmp_path, completion).run_cell(
        cell_id="s:a:w0", package={"instruction.md": "Edit"}
    )
    assert FakeSandbox.created[0].interrupted
    assert [e["kind"] for e in result.trajectory["events"]].count("tool_timeout") == 1
    tool = next(m for m in result.trajectory["messages"] if m["role"] == "tool")
    assert "killed" in tool["content"]


def test_model_dispatch_failure_is_named(tmp_path: Path) -> None:
    def failing(**kwargs: Any) -> ModelTurn:
        raise ModelDispatchError("MachineIdentityMismatch", "moved")

    with pytest.raises(AgentLoopError, match="model_dispatch:MachineIdentityMismatch"):
        _local(tmp_path, failing).run_cell(cell_id="s:a:w0", package={"instruction.md": "E"})


@pytest.mark.parametrize(
    ("path", "cause"),
    [
        ("package.json", "tampering"),
        ("tests/hidden.test.ts", "tampering"),
        ("src/package.json", "tampering"),
        ("tests/visible/tsconfig.json", "tampering"),
        ("notes.txt", "out_of_scope_edit"),
    ],
)
def test_out_of_scope_submission_is_rejected_with_its_files(
    tmp_path: Path, path: str, cause: str
) -> None:
    completion = Scripted(
        [_call("write_file", {"path": path, "content": "changed"}, 1)],
        [_call("submit_output", {"summary": "s"}, 2)],
    )
    with pytest.raises(AgentLoopError) as failure:
        _local(tmp_path, completion, writable_prefixes=("src/", "tests/visible/")).run_cell(
            cell_id="s:a:w0",
            package={"instruction.md": "Edit", "workspace/package.json": "{}"},
        )
    assert failure.value.cause == cause
    assert failure.value.rejection is not None
    assert failure.value.rejection.artifacts[path] == b"changed"


@pytest.mark.parametrize(
    ("peaks", "cause"),
    [
        ({"oom_kills": 1, "workspace_free_kb": 9999, "cache_free_kb": 9999}, "memory_limit"),
        ({"oom_kills": 0, "workspace_free_kb": 12, "cache_free_kb": 9999}, "storage_exhausted"),
        ({"oom_kills": 0, "workspace_free_kb": 9999, "cache_free_kb": 0}, "storage_exhausted"),
    ],
)
def test_exhausted_ceilings_fail_the_submission(
    tmp_path: Path, peaks: dict[str, int], cause: str
) -> None:
    FakeSandbox.peaks = peaks
    completion = Scripted([_call("submit_output", {"summary": "s"}, 1)])
    with pytest.raises(AgentLoopError) as failure:
        _local(tmp_path, completion).run_cell(cell_id="s:a:w0", package={"instruction.md": "E"})
    assert failure.value.cause == cause


HEALTHY = {"oom_kills": 0, "workspace_free_kb": 9999, "cache_free_kb": 9999}


def test_recovered_oom_kill_is_recorded_but_keeps_the_submission(tmp_path: Path) -> None:
    FakeSandbox.peaks = dict(HEALTHY)
    completion = Scripted(
        [_call("run_command", {"command": "oom"}, 1)],
        [_call("write_file", {"path": "src/a.ts", "content": "fixed"}, 2)],
        [_call("submit_output", {"summary": "s"}, 3)],
    )
    result = _local(tmp_path, completion, writable_prefixes=("src/",)).run_cell(
        cell_id="s:a:w0", package={"instruction.md": "E", "workspace/src/a.ts": "one"}
    )
    assert b"+fixed" in result.patch
    events = result.trajectory["events"]
    assert [e for e in events if e["kind"] == "oom_kill"] == [
        {"kind": "oom_kill", "turn": 1, "tool": "run_command", "oom_kills": 1, "total": 1}
    ]
    peaks = next(e for e in events if e["kind"] == "cgroup_peaks")
    assert peaks["oom_kills"] == peaks["oom_kills_seen_by_tools"] == 1


def test_oom_kill_after_the_last_tool_result_is_memory_limit(tmp_path: Path) -> None:
    FakeSandbox.peaks = dict(HEALTHY)
    completion = Scripted(
        [_call("run_command", {"command": "oom"}, 1)],
        [_call("run_command", {"command": "oom-later"}, 2)],
        [_call("submit_output", {"summary": "s"}, 3)],
    )
    with pytest.raises(AgentLoopError) as failure:
        _local(tmp_path, completion).run_cell(cell_id="s:a:w0", package={"instruction.md": "E"})
    assert failure.value.cause == "memory_limit"
    # The kill the model saw stays recorded; the one at submission voids the tree.
    events = failure.value.trajectory["events"]
    assert [e["total"] for e in events if e["kind"] == "oom_kill"] == [1]
    assert "candidate.patch" in failure.value.evidence


@pytest.mark.parametrize(
    "peaks",
    [
        {"oom_kills": 1, "workspace_free_kb": 9999, "cache_free_kb": 9999},
        {"oom_kills": 0, "workspace_free_kb": 9999, "cache_free_kb": 0},
    ],
)
def test_scope_and_tampering_outrank_resource_causes(
    tmp_path: Path, peaks: dict[str, int]
) -> None:
    FakeSandbox.peaks = peaks
    completion = Scripted(
        [_call("write_file", {"path": "package.json", "content": "{\"x\":1}"}, 1)],
        [_call("submit_output", {"summary": "s"}, 2)],
    )
    with pytest.raises(AgentLoopError) as failure:
        _local(tmp_path, completion, writable_prefixes=("src/",)).run_cell(
            cell_id="s:a:w0", package={"instruction.md": "E", "workspace/package.json": "{}"}
        )
    assert failure.value.cause == "tampering"


def test_nested_git_metadata_in_a_submission_is_out_of_scope(tmp_path: Path) -> None:
    completion = Scripted(
        [_call("write_file", {"path": "src/x/.git", "content": "gitdir: /elsewhere"}, 1)],
        [_call("submit_output", {"summary": "s"}, 2)],
    )
    with pytest.raises(AgentLoopError) as failure:
        _local(tmp_path, completion, writable_prefixes=("src/",)).run_cell(
            cell_id="s:a:w0", package={"instruction.md": "E", "workspace/src/a.ts": "one"}
        )
    assert failure.value.cause == "out_of_scope_edit"
    assert failure.value.rejection is not None
    assert failure.value.rejection.rejected_path == "src/x/.git"


def test_final_submission_may_follow_a_tool_in_the_same_model_turn(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        answer = _answer("run_command", {"command": "true"}, 1)
        answer["choices"][0]["message"]["tool_calls"].append(
            _call("submit_output", {"summary": "done"}, 2)
        )
        return httpx.Response(200, json=answer)

    result = _client(tmp_path, handler).run_cell(
        cell_id="s:a:w0", package={"instruction.md": "Edit", "workspace/a.txt": "one"}
    )
    assert result.summary == "done"
    assert result.requests == 1
    assert [event["kind"] for event in result.trajectory["events"]][-1] == "submitted"


def test_hidden_test_package_entries_never_reach_tools(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_answer("submit_output", {"summary": ""}, 1))

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
        return httpx.Response(200, json=_answer("submit_output", {"summary": "ok"}, calls))

    bounds = LoopBounds(max_conversation_bytes=950, max_tool_output_bytes=20)
    result = _client(tmp_path, handler, bounds=bounds).run_cell(
        cell_id="s:a:w0", package={"instruction.md": "Edit"}
    )
    kinds = [event["kind"] for event in result.trajectory["events"]]
    assert "tool_output_truncated" in kinds
    assert "conversation_truncated" in kinds
    assert result.requests == 5


def test_tool_schemas_are_fixed_ordered_and_under_their_byte_cap() -> None:
    encoded = json.dumps(TOOLS, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    assert [tool["function"]["name"] for tool in TOOLS] == [
        "read_file", "write_file", "replace_in_file", "run_command", "submit_output"
    ]
    # Pinned: a schema change is a new image and is requalified, never drift.
    assert len(encoded) == 1_870
    assert len(encoded) <= LoopBounds().max_tool_schema_bytes
    for tool in TOOLS:
        parameters = tool["function"]["parameters"]
        assert parameters["required"] == list(parameters["properties"])


def _tool_results(result: Any) -> list[str]:
    return [m["content"] for m in result.trajectory["messages"] if m["role"] == "tool"]


def _read_pages(tmp_path: Path, text: str, cap: int, **arguments: Any) -> list[str]:
    """Follow read_file's truncation notes until the requested range is exhausted."""
    pages: list[str] = []
    start = arguments.pop("start_line", None)
    while len(pages) < 50:
        completion = Scripted(
            [_call("read_file", {"path": "big.ts", "start_line": start, **arguments}, 1)],
            [_call("submit_output", {"summary": "s"}, 2)],
        )
        FakeSandbox.created.clear()
        result = _local(
            tmp_path / str(len(pages)), completion,
            bounds=LoopBounds(max_tool_output_bytes=cap),
        ).run_cell(cell_id="s:a:w0", package={"instruction.md": "E", "workspace/big.ts": text})
        page = _tool_results(result)[0]
        assert len(page.encode("utf-8")) <= cap
        assert page.startswith("exit=0\n")
        pages.append(page.removeprefix("exit=0\n"))
        if "continue with start_line=" not in page:
            return pages
        start = int(page.rsplit("start_line=", 1)[1].rstrip("]"))
    raise AssertionError("read_file never reached the end of the range")


def test_read_file_pages_a_file_larger_than_the_tool_output_cap(tmp_path: Path) -> None:
    text = "".join(f"export const line{n} = {n};\n" for n in range(1, 201))
    pages = _read_pages(tmp_path, text, cap=1_024)
    assert len(pages) > 1
    first = pages[0]
    assert "[truncated at the tool output limit: showed lines 1-" in first
    assert "of 200;" in first and "lines of the requested range remain" in first
    bodies = [page.split("[truncated", 1)[0] for page in pages]
    assert "".join(bodies) == text


def test_read_file_returns_an_inclusive_line_range(tmp_path: Path) -> None:
    completion = Scripted(
        [_call("read_file", {"path": "a.ts", "start_line": 2, "end_line": 3}, 1),
         _call("read_file", {"path": "a.ts", "start_line": 4, "end_line": None}, 1),
         _call("read_file", {"path": "a.ts"}, 1)],
        [_call("submit_output", {"summary": "s"}, 2)],
    )
    text = "one\ntwo\r\nthree\nfour"
    result = _local(tmp_path, completion).run_cell(
        cell_id="s:a:w0", package={"instruction.md": "E", "workspace/a.ts": text}
    )
    assert _tool_results(result) == [
        "exit=0\ntwo\r\nthree\n", "exit=0\nfour", f"exit=0\n{text}"
    ]


def test_read_file_cuts_a_single_overlong_line_and_says_so(tmp_path: Path) -> None:
    text = "short\n" + "x" * 5_000 + "\ntail\n"
    pages = _read_pages(tmp_path, text, cap=1_024, start_line=2)
    assert "line 2 alone exceeds the tool output limit" in pages[0]
    assert "continue with start_line=3" in pages[0]
    assert pages[-1] == "tail\n"


@pytest.mark.parametrize(
    ("arguments", "reason"),
    [
        ({"path": "a.ts", "start_line": 9}, "start_line 9 is past the end of a.ts (2 lines)"),
        ({"path": "a.ts", "start_line": 2, "end_line": 1}, "end_line must not be before"),
        ({"path": "a.ts", "start_line": 0}, "start_line must be a positive integer"),
        ({"path": "a.ts", "end_line": "2"}, "end_line must be a positive integer"),
        ({"path": "missing.ts"}, "No such file or directory: missing.ts"),
        ({"path": "a.ts", "line": 1}, "unknown tool or argument fields"),
    ],
)
def test_read_file_mistakes_are_tool_errors(
    tmp_path: Path, arguments: dict[str, Any], reason: str
) -> None:
    completion = Scripted(
        [_call("read_file", arguments, 1)], [_call("submit_output", {"summary": "s"}, 2)]
    )
    result = _local(tmp_path, completion).run_cell(
        cell_id="s:a:w0", package={"instruction.md": "E", "workspace/a.ts": "a\nb\n"}
    )
    (content,) = _tool_results(result)
    assert content.startswith("error: ") and reason in content
    assert [e["kind"] for e in result.trajectory["events"]].count("tool_error") == 1


def test_replace_in_file_edits_exactly_one_occurrence(tmp_path: Path) -> None:
    completion = Scripted(
        [_call("replace_in_file", {"path": "src/a.ts", "old": "b = 1", "new": "b = 2"}, 1)],
        [_call("submit_output", {"summary": "s"}, 2)],
    )
    result = _local(tmp_path, completion, writable_prefixes=("src/",)).run_cell(
        cell_id="s:a:w0",
        package={"instruction.md": "E", "workspace/src/a.ts": "a = 1\r\nb = 1\r\nc = 1\r\n"},
    )
    assert _tool_results(result) == ["exit=0\nreplaced 1 occurrence in src/a.ts"]
    assert result.files == {"src/a.ts": b"a = 1\r\nb = 2\r\nc = 1\r\n"}


@pytest.mark.parametrize(
    ("arguments", "reason"),
    [
        ({"path": "src/a.ts", "old": "absent", "new": "x"}, "old occurs 0 times in src/a.ts"),
        ({"path": "src/a.ts", "old": "= 1", "new": "= 2"}, "old occurs 2 times in src/a.ts"),
        ({"path": "src/a.ts", "old": "", "new": "x"}, "old must be a non-empty string"),
        ({"path": "src/missing.ts", "old": "a", "new": "x"}, "No such file or directory"),
        ({"path": "../a.ts", "old": "a", "new": "x"}, "unsafe path"),
        ({"path": "src/link.ts", "old": "a", "new": "x"}, "path resolves outside /workspace"),
        ({"path": "src/a.ts", "old": "a"}, "unknown tool or argument fields"),
    ],
)
def test_replace_in_file_refusals_change_nothing_and_reach_the_model(
    tmp_path: Path, arguments: dict[str, Any], reason: str
) -> None:
    outside = tmp_path / "outside.ts"
    outside.write_text("a = 1\n")

    class LinkingSandbox(FakeSandbox):
        def __init__(self, workspace: Path, cache: Path, image: str, cell_id: str) -> None:
            super().__init__(workspace, cache, image, cell_id)
            (workspace / "src" / "link.ts").symlink_to(outside)

    completion = Scripted(
        [_call("replace_in_file", arguments, 1)], [_call("submit_output", {"summary": "s"}, 2)]
    )
    with pytest.raises(AgentLoopError) as failure:
        # The planted link is itself an escaping symlink at capture, which
        # proves the refusal left the cell running to its submission.
        _local(
            tmp_path / "runs", completion, sandbox_factory=LinkingSandbox,
            writable_prefixes=("src/",),
        ).run_cell(
            cell_id="s:a:w0",
            package={"instruction.md": "E", "workspace/src/a.ts": "a = 1\nb = 1\n"},
        )
    assert failure.value.cause == "escaping_symlink"
    messages = failure.value.trajectory["messages"]
    (content,) = [m["content"] for m in messages if m["role"] == "tool"]
    assert content.startswith("error: ") and reason in content
    assert outside.read_text() == "a = 1\n"
    assert failure.value.rejection is not None
    assert failure.value.rejection.artifacts["src/a.ts"] == b"a = 1\nb = 1\n"


def test_truncated_tool_output_says_so_within_the_cap(tmp_path: Path) -> None:
    completion = Scripted(
        [_call("run_command", {"command": "noisy"}, 1)],
        [_call("submit_output", {"summary": "s"}, 2)],
    )
    result = _local(
        tmp_path, completion, bounds=LoopBounds(max_tool_output_bytes=100)
    ).run_cell(cell_id="s:a:w0", package={"instruction.md": "E"})
    (content,) = _tool_results(result)
    note = "[output truncated at the 100-byte tool output limit; 107 bytes in all]"
    assert content.startswith("exit=0\nxx") and content.endswith(note)
    assert len(content.encode("utf-8")) <= 100


@pytest.mark.parametrize("calls", [[], [_call("run_command", {"command": "true"}, 1)]])
def test_a_cut_off_turn_keeps_its_text(tmp_path: Path, calls: list[dict[str, Any]]) -> None:
    runaway = "export function f() {\n" + "  // again\n" * 200
    completion = Scripted(
        calls, finish="length", content=runaway, completion_tokens=8_192
    )
    with pytest.raises(AgentLoopError) as failure:
        _local(tmp_path, completion).run_cell(cell_id="s:a:w0", package={"instruction.md": "E"})
    cut = [e for e in failure.value.trajectory["events"] if e["kind"] == "output_cut_off"]
    assert cut and cut[0]["turn"] == 1 and cut[0]["content"] == runaway
    assert cut[0]["tool_calls"] == calls
    assert failure.value.cause == ("output_token_limit" if not calls else "turn_limit")


def _assert_no_orphaned_tool_results(messages: list[dict[str, Any]]) -> None:
    assert [m["role"] for m in messages[:2]] == ["system", "user"]
    pending: set[str] = set()
    for message in messages[2:]:
        if message["role"] == "assistant":
            assert not pending, "an exchange lost some of its tool results"
            pending = {call["id"] for call in message["tool_calls"]}
        else:
            assert message["role"] == "tool"
            assert message["tool_call_id"] in pending, "a tool result outlived its call"
            pending.discard(message["tool_call_id"])


def test_conversation_truncation_never_orphans_tool_results(tmp_path: Path) -> None:
    def turn_calls(turn: int) -> list[dict[str, Any]]:
        return [
            {**_call("run_command", {"command": "echo"}, turn), "id": f"call-{turn}-{n}"}
            for n in range(turn % 3 + 1)
        ] + [{**_call("read_file", {"path": "a.ts", "start_line": 1}, turn),
              "id": f"read-{turn}"}]

    completion = Scripted(*(turn_calls(turn) for turn in range(1, 21)))
    bounds = LoopBounds(max_conversation_bytes=2_500)
    with pytest.raises(AgentLoopError) as failure:
        _local(tmp_path, completion, bounds=bounds).run_cell(
            cell_id="s:a:w0", package={"instruction.md": "E", "workspace/a.ts": "a\n" * 40}
        )
    assert failure.value.cause == "turn_limit"
    events = failure.value.trajectory["events"]
    assert any(e["kind"] == "conversation_truncated" for e in events)
    for seen in completion.seen:
        _assert_no_orphaned_tool_results(seen["messages"])
        assert len(json.dumps(seen["messages"], separators=(",", ":")).encode()) <= 2_500


def test_container_uid_can_write_materialized_repository_and_cache(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_answer("submit_output", {"summary": "done"}, 1))

    _client(tmp_path, handler).run_cell(
        cell_id="s:a:w0",
        package={"instruction.md": "Edit", "workspace/sub/a.txt": "original"},
    )
    sandbox = FakeSandbox.created[0]
    assert sandbox.workspace_mode == sandbox.cache_mode == 0o777
    assert sandbox.modes == {"sub": 0o777, "sub/a.txt": 0o666}


def test_bridge_loop_bounds_match_dedicated_config() -> None:
    from dataclasses import asdict

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
    } == {"attempts": 1, "concurrency": 1, "provider_retries": 0, "sdk_retries": 0}


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
    assert failure.value.trajectory["events"][-1]["requests"] == 0


def test_full_provider_envelope_limit_does_not_count_a_request(tmp_path: Path) -> None:
    dispatched = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal dispatched
        dispatched += 1
        return httpx.Response(200, json=_answer("submit_output", {"summary": "ok"}, 1))

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "Edit"},
    ]
    compact_size = sum(len(json.dumps(value, separators=(",", ":")).encode())
                       for value in (messages, TOOLS))
    client = _client(tmp_path, handler, bounds=replace(LoopBounds(),
                                                      max_request_bytes=compact_size + 1))
    with pytest.raises(AgentLoopError, match="request_limit") as failure:
        client.run_cell(cell_id="s:a:w0", package={"instruction.md": "Edit"})
    assert failure.value.usage["requests"] == 0
    assert failure.value.usage["cost_usd"] == 0.0
    assert failure.value.trajectory["turns"][0]["usage"]["requests"] == 0
    assert dispatched == 0


@pytest.mark.parametrize("failure_kind", ["shape", "identity", "response_limit", "cost"])
def test_billed_200_failure_keeps_turn_and_cell_usage(
    tmp_path: Path, failure_kind: str
) -> None:
    body = _answer("submit_output", {"summary": "ok"}, 1)
    bounds = LoopBounds()
    if failure_kind == "shape":
        body["choices"] = []
    elif failure_kind == "identity":
        body["model"] = "wrong/model"
    elif failure_kind == "response_limit":
        bounds = replace(bounds, max_response_bytes=1)
    else:
        del body["usage"]["cost"]

    client = _client(tmp_path, lambda request: httpx.Response(200, json=body), bounds=bounds)
    with pytest.raises(AgentLoopError) as failure:
        client.run_cell(cell_id="s:a:w0", package={"instruction.md": "Edit"})
    assert failure.value.cause == {
        "shape": "provider_response", "identity": "provider_identity",
        "response_limit": "response_limit", "cost": "provider_usage",
    }[failure_kind]
    expected_cost = None if failure_kind == "cost" else 0.001
    assert failure.value.usage == {
        "prompt_tokens": 10, "completion_tokens": 5, "requests": 1,
        "cost_usd": expected_cost,
    }
    assert failure.value.trajectory["turns"][0]["usage"] == failure.value.usage


@pytest.mark.parametrize(("missing_field", "bad_value"), [
    ("completion_tokens", None), ("prompt_tokens", "not-a-count"),
])
@pytest.mark.parametrize("earlier_response", [False, True])
def test_billed_200_unknown_token_count_keeps_readable_usage(
    tmp_path: Path, missing_field: str, bad_value: object, earlier_response: bool,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if earlier_response and calls == 1:
            return httpx.Response(200, json=_answer("run_command", {"command": "true"}, 1))
        body = _answer("submit_output", {"summary": "ok"}, calls)
        if bad_value is None:
            del body["usage"][missing_field]
        else:
            body["usage"][missing_field] = bad_value
        return httpx.Response(200, json=body)

    with pytest.raises(AgentLoopError, match="provider_usage") as failure:
        _client(tmp_path, handler).run_cell(
            cell_id="s:a:w0", package={"instruction.md": "Edit"}
        )
    expected = {
        "prompt_tokens": None if missing_field == "prompt_tokens" else 10 * calls,
        "completion_tokens": None if missing_field == "completion_tokens" else 5 * calls,
        "requests": calls,
        "cost_usd": 0.001 * calls,
    }
    assert failure.value.usage == expected
    assert failure.value.trajectory["turns"][0]["usage"] == expected


@pytest.mark.parametrize("read_error", [httpx.ReadError, httpx.ReadTimeout])
@pytest.mark.parametrize("earlier_response", [False, True])
def test_read_failure_after_dispatch_marks_cost_unknown(
    tmp_path: Path, read_error: type[httpx.RequestError], earlier_response: bool,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if earlier_response and calls == 1:
            return httpx.Response(200, json=_answer("run_command", {"command": "true"}, 1))

        class BrokenStream(httpx.SyncByteStream):
            def __iter__(self) -> Iterator[bytes]:
                yield b'{"partial":'
                raise read_error("response read failed", request=request)

        return httpx.Response(200, stream=BrokenStream())

    with pytest.raises(AgentLoopError, match="transport_failure") as failure:
        _client(tmp_path, handler).run_cell(
            cell_id="s:a:w0", package={"instruction.md": "Edit"}
        )
    expected = {
        "prompt_tokens": 10 if earlier_response else 0,
        "completion_tokens": 5 if earlier_response else 0,
        "requests": calls,
        "cost_usd": None,
    }
    assert failure.value.usage == expected
    assert failure.value.trajectory["turns"][0]["usage"] == expected


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
        return httpx.Response(200, json=_answer("submit_output", {"summary": "ok"}, 1))

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


def _inspect_stdout() -> str:
    host = {
        "NetworkMode": "none", "ReadonlyRootfs": True, "Memory": 1610612736,
        "PidsLimit": 128, "NanoCpus": 1000000000, "CapDrop": ["ALL"],
        "Tmpfs": {"/workspace": "size=256m,mode=1777", "/cache": "size=256m,mode=1777"},
    }
    return json.dumps(host) + "|" + json.dumps("1000:1000")


def test_docker_sandbox_mounts_only_neutral_cell_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: Any) -> Any:
        commands.append(command)
        stdout = _inspect_stdout() if command[:2] == ["docker", "inspect"] else "ok"
        return type("Result", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()

    monkeypatch.setattr("assay_pier_bridge.agent_loop.subprocess.run", fake_run)
    workspace, cache = tmp_path / "workspace", tmp_path / "cache"
    sandbox = DockerToolSandbox(workspace, cache, "locked-image", "s:a:w0")
    assert sandbox.observed["network_mode"] == "none"
    assert sandbox.observed["user"] == "1000:1000"
    sandbox.close()
    command = commands[0]
    assert command[:3] == ["docker", "run", "-d"]
    assert command[command.index("--network") + 1] == "none"
    assert command[command.index("--label") + 1] == "assay-cell=s:a:w0"
    assert f"{workspace}:/workspace:rw" in command
    assert f"{cache}:/cache:rw" in command
    assert "HOME=/cache" in command
    assert not any("hidden" in arg for arg in command)
    assert commands[-1][:3] == ["docker", "rm", "-f"]


def test_concurrent_sandbox_close_removes_container_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered_removal = Event()
    release_removal = Event()
    second_started = Event()
    removals: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: Any) -> Any:
        if command[:3] == ["docker", "rm", "-f"]:
            removals.append(command)
            entered_removal.set()
            assert release_removal.wait(2)
        stdout = _inspect_stdout() if command[:2] == ["docker", "inspect"] else "ok"
        return type("Result", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()

    monkeypatch.setattr("assay_pier_bridge.agent_loop.subprocess.run", fake_run)
    sandbox = DockerToolSandbox(tmp_path / "workspace", tmp_path / "cache", "img", "s:a:w0")

    def second_close() -> None:
        second_started.set()
        sandbox.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(sandbox.close)
        assert entered_removal.wait(2)
        second = pool.submit(second_close)
        assert second_started.wait(2)
        time.sleep(0.05)
        release_removal.set()
        first.result(timeout=2)
        second.result(timeout=2)
    assert len(removals) == 1


def test_failed_sandbox_close_can_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = 0

    def fake_run(command: list[str], **kwargs: Any) -> Any:
        nonlocal attempts
        if command[:3] == ["docker", "rm", "-f"]:
            attempts += 1
            return type("Result", (), {"returncode": int(attempts == 1)})()
        stdout = _inspect_stdout() if command[:2] == ["docker", "inspect"] else "ok"
        return type("Result", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()

    monkeypatch.setattr("assay_pier_bridge.agent_loop.subprocess.run", fake_run)
    sandbox = DockerToolSandbox(tmp_path / "workspace", tmp_path / "cache", "img", "s:a:w0")
    with pytest.raises(RuntimeError, match="container_cleanup"):
        sandbox.close()
    sandbox.close()
    assert attempts == 2


def test_tmpfs_sandbox_takes_its_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: Any) -> Any:
        commands.append(command)
        stdout = _inspect_stdout() if command[:2] == ["docker", "inspect"] else ""
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr("assay_pier_bridge.agent_loop.subprocess.run", fake_run)
    limits = SandboxLimits(memory_mb=900, pids=40, cpus=2.0, workspace_mb=100, cache_mb=50,
                           tmp_mb=25)
    DockerToolSandbox(tmp_path, tmp_path, "img", "s:a:w0", tmpfs_storage=True, limits=limits)
    run = commands[0]
    assert "/workspace:size=100m,mode=1777" in run and "/cache:size=50m,mode=1777" in run
    assert "/tmp:size=25m" in run
    assert run[run.index("--memory") + 1] == "900m"
    assert run[run.index("--pids-limit") + 1] == "40"
    assert run[run.index("--cpus") + 1] == "2.0"


def test_sandbox_limits_keep_memory_above_tmpfs() -> None:
    with pytest.raises(ValueError, match="memory_mb must exceed"):
        SandboxLimits(memory_mb=700, workspace_mb=256, cache_mb=256, tmp_mb=256)


def test_tmpfs_archive_failure_removes_started_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    def fail_archive(*args: Any, **kwargs: Any) -> Any:
        raise OSError("archive failed")

    monkeypatch.setattr("assay_pier_bridge.agent_loop.subprocess.run", fake_run)
    monkeypatch.setattr("assay_pier_bridge.agent_loop.tarfile.open", fail_archive)
    with pytest.raises(ContainerStartError):
        DockerToolSandbox(tmp_path, tmp_path, "locked-image", "s:a:w0", tmpfs_storage=True)
    assert commands[0][:3] == ["docker", "run", "-d"]
    assert commands[-1][:3] == ["docker", "rm", "-f"]


def test_tmpfs_transfer_timeout_removes_started_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command[:3] == ["docker", "exec", "-i"]:
            raise subprocess.TimeoutExpired(command, 30)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("assay_pier_bridge.agent_loop.subprocess.run", fake_run)
    with pytest.raises(ContainerStartError):
        DockerToolSandbox(tmp_path, tmp_path, "locked-image", "s:a:w0", tmpfs_storage=True)
    assert commands[-1][:3] == ["docker", "rm", "-f"]


def _tar(entries: list[tarfile.TarInfo], data: dict[str, bytes] | None = None) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as stream:
        for entry in entries:
            content = (data or {}).get(entry.name)
            stream.addfile(entry, io.BytesIO(content) if content is not None else None)
    return buffer.getvalue()


def _file(name: str, content: bytes) -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name)
    info.size = len(content)
    return info, content


def test_tmpfs_capture_streams_the_tree_and_replaces_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "deleted.txt").write_text("old")
    sandbox = DockerToolSandbox.__new__(DockerToolSandbox)
    sandbox.name = "fake-container"
    sandbox._tmpfs_storage = True
    sandbox._workspace = workspace
    sandbox.execute = lambda *args, **kwargs: ToolOutput(  # type: ignore[method-assign]
        "exit=0\n1024\n2\n0\n5000\n6000\n", 30, False
    )
    directory = tarfile.TarInfo("./src")
    directory.type = tarfile.DIRTYPE
    info, content = _file("./src/new.txt", b"new")
    archive = _tar([directory, info], {"./src/new.txt": content})

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        assert command[:5] == ["docker", "exec", "-u", "0:0", "fake-container"]
        return subprocess.CompletedProcess(command, 0, archive, b"")

    monkeypatch.setattr("assay_pier_bridge.agent_loop.subprocess.run", fake_run)
    assert sandbox.capture_workspace() == {
        "memory_peak_bytes": 1024, "pids_peak": 2, "oom_kills": 0,
        "workspace_free_kb": 5000, "cache_free_kb": 6000,
    }
    assert not (workspace / "deleted.txt").exists()
    assert (workspace / "src" / "new.txt").read_text() == "new"


@pytest.mark.parametrize(
    ("tmpfs", "stdout", "expected"),
    [(True, "exit=0\n3\n", 3), (False, "unused", None),
     (True, "exit=1\ngrep: no such file\n", "error"), (True, "exit=0\nmany\n", "error")],
)
def test_docker_sandbox_reads_the_cgroup_oom_kill_count(
    tmpfs: bool, stdout: str, expected: int | str | None
) -> None:
    sandbox = DockerToolSandbox.__new__(DockerToolSandbox)
    sandbox._tmpfs_storage = tmpfs
    seen: list[list[str]] = []

    def execute(argv: list[str], **kwargs: Any) -> ToolOutput:
        seen.append(argv)
        return ToolOutput(stdout, len(stdout), False)

    sandbox.execute = execute  # type: ignore[method-assign]
    if expected == "error":
        with pytest.raises(RuntimeError, match="cgroup_peak_observation"):
            sandbox.oom_kills()
        return
    assert sandbox.oom_kills() == expected
    assert bool(seen) is tmpfs
    if seen:
        assert "/sys/fs/cgroup/memory.events" in seen[0][-1]


@pytest.mark.parametrize(
    ("kind", "cause"),
    [("symlink", "escaping_symlink"), ("fifo", "out_of_scope_edit"),
     ("traversal", "traversal")],
)
def test_archive_extraction_rejects_links_specials_and_escapes(
    tmp_path: Path, kind: str, cause: str
) -> None:
    kept, kept_content = _file("./a.txt", b"kept")
    if kind == "symlink":
        bad = tarfile.TarInfo("./link")
        bad.type = tarfile.SYMTYPE
        bad.linkname = "/etc/passwd"
    elif kind == "fifo":
        bad = tarfile.TarInfo("./pipe")
        bad.type = tarfile.FIFOTYPE
    else:
        bad, _ = _file("../escape.txt", b"")
    archive = _tar([kept, bad], {"./a.txt": kept_content})
    with pytest.raises(ArtifactCollectionRejected) as rejection:
        extract_workspace_archive(archive, tmp_path)
    assert rejection.value.cause == cause
    assert rejection.value.artifacts == {"a.txt": b"kept"}
    assert not (tmp_path.parent / "escape.txt").exists()


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


def test_failed_container_start_keeps_named_cause_and_records_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, "", "failed")

    monkeypatch.setattr("assay_pier_bridge.agent_loop.subprocess.run", fake_run)
    with pytest.raises(ContainerStartError) as start:
        DockerToolSandbox(tmp_path / "workspace", tmp_path / "cache", "locked-image", "s:a:w0")
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


def test_tmpfs_capture_permission_failure_has_candidate_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox = DockerToolSandbox.__new__(DockerToolSandbox)
    sandbox.name = "fake-container"
    sandbox._tmpfs_storage = True
    sandbox._workspace = tmp_path
    sandbox.execute = lambda *a, **k: ToolOutput(  # type: ignore[method-assign]
        "exit=0\n1\n2\n0\n5000\n6000\n", 25, False
    )
    monkeypatch.setattr(
        "assay_pier_bridge.agent_loop.subprocess.run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, 1, b"", b"tar: Permission denied"
        ),
    )
    with pytest.raises(ArtifactCollectionRejected) as rejected:
        sandbox.capture_workspace()
    assert rejected.value.cause == "workspace_capture_permission"


def test_archive_hard_link_has_distinct_candidate_cause(tmp_path: Path) -> None:
    member = tarfile.TarInfo("linked.txt")
    member.type = tarfile.LNKTYPE
    member.linkname = "inside.txt"
    with pytest.raises(ArtifactCollectionRejected) as rejected:
        extract_workspace_archive(_tar([member]), tmp_path)
    assert rejected.value.cause == "hard_link_submission"


def test_reply_without_a_tool_call_keeps_its_text(tmp_path: Path) -> None:
    completion = Scripted([], finish="stop", content="Review: the migration looks complete.")
    with pytest.raises(AgentLoopError) as failure:
        _local(tmp_path, completion).run_cell(
            cell_id="s:a:w0", package={"instruction.md": "Edit", "workspace/src/a.ts": "a\n"},
        )
    assert failure.value.cause == "no_tool_call"
    replies = [event for event in failure.value.trajectory["events"]
               if event["kind"] == "reply_without_tool_call"]
    assert replies == [{"kind": "reply_without_tool_call", "turn": 1, "finish_reason": "stop",
                        "content": "Review: the migration looks complete."}]
