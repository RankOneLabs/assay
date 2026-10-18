"""The Assay/bridge boundary: Smithers-driven turns and PierAdapter settlement."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from assay.adapters.pier import PierAdapter
from assay.adapters.smithers import SmithersFactory
from assay.execution import WorkerFailure, WorkerSuccess
from assay.models import CellCoordinate
from assay.pier_protocol import RuntimeBinding
from assay.store import ObjectStore
from workflow_edit.bridge import (
    LOCAL_ROUTE,
    WRITABLE_PREFIXES,
    ModelDispatchError,
    ModelTurn,
    SmithersTurnCompletion,
    ToolOutput,
    WorkflowEditBridgeClient,
    trial_limits,
)

ROUTING = (
    "machines:\n  mcbain:\n    backend: vllm\n"
    "models:\n  qwen-coder-32b:\n    machines: [mcbain]\n"
    "    backend_tags:\n      vllm: {tag}\n"
)


def test_workflow_edit_agent_identity_digests_are_stable() -> None:
    # Import after workflow_edit.bridge has added the isolated Pier source path.
    from assay_pier_bridge.agent_loop import LoopBounds, SandboxLimits
    from assay_pier_bridge.repository_trial import agent_configuration

    configuration = agent_configuration(
        bounds=LoopBounds(), limits=SandboxLimits(),
        writable_prefixes=WRITABLE_PREFIXES, model_route=LOCAL_ROUTE,
    )
    assert configuration["tools_sha256"] == (
        "sha256:0c99814308ccae7f60e1b3746f40053394e719dfbee07e81e5e9c302d258b45c"
    )
    assert configuration["system_prompt_sha256"] == (
        "sha256:ce5624bdacced169592ba1bb129d0c8ff78c660f747a5b430aa01a55325e4fdf"
    )


def _factory(tmp_path: Path, tag: str = "/models/coder") -> SmithersFactory:
    routing = tmp_path / "routing_config.yaml"
    routing.write_text(ROUTING.format(tag=tag))
    return SmithersFactory(
        model="qwen-coder-32b", machine="mcbain", routing_config=routing,
        dispatch_url="http://smithers.test", poll_interval=0,
    )


def _smithers(tool_calls: list[dict[str, Any]], *, output_tokens: int = 40) -> httpx.MockTransport:
    created = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)
    posts: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.host == "mcbain":
            return httpx.Response(200, json={
                "job_id": "job-1", "status": "complete",
                "usage": {"model": "/models/coder", "input_tokens": 900,
                          "output_tokens": output_tokens},
            })
        if request.method == "POST":
            posts.append(json.loads(request.content))
            return httpx.Response(200, json={"job_id": "job-1"})
        return httpx.Response(200, json={
            "job_id": "job-1", "status": "complete", "model": "qwen-coder-32b",
            "machine": "mcbain", "created_at": created.isoformat(),
            "started_at": (created + timedelta(seconds=1)).isoformat(),
            "completed_at": (created + timedelta(seconds=9)).isoformat(),
            "result": {"content": "", "tool_calls": tool_calls},
        })

    transport = httpx.MockTransport(respond)
    transport.posts = posts  # type: ignore[attr-defined]
    return transport


def _install(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> None:
    original = httpx.AsyncClient.__init__

    def patched(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> None:
        kwargs["transport"] = transport
        original(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)


CALL = {"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}


def test_turn_is_one_keyed_job_with_attested_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = _smithers([CALL])
    _install(monkeypatch, transport)
    completion = SmithersTurnCompletion(_factory(tmp_path), "cell-key")
    turn = completion(messages=[{"role": "user", "content": "x"}], tools=[], max_tokens=512,
                      turn=3, deadline=None)
    assert isinstance(turn, ModelTurn)
    assert turn.message["tool_calls"] == [CALL]
    assert (turn.prompt_tokens, turn.completion_tokens, turn.cost_usd) == (900, 40, None)
    assert turn.finish_reason == "tool_calls"
    assert turn.observations["worker_model"] == "/models/coder"
    assert turn.observations["time_from_acceptance_seconds"] == 8.0
    submitted = transport.posts[0]  # type: ignore[attr-defined]
    assert submitted["idempotency_key"] == "cell-key:t3"
    assert submitted["machine"] == "mcbain" and submitted["max_retries"] == 0
    assert submitted["payload"]["tool_choice"] == "required"


def test_a_completion_at_the_cap_is_reported_cut_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, _smithers([], output_tokens=512))
    turn = SmithersTurnCompletion(_factory(tmp_path), "k")(
        messages=[], tools=[], max_tokens=512, turn=1, deadline=None
    )
    assert turn.finish_reason == "length"


def test_routing_changed_after_authorization_fails_the_turn(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    authorized = factory.configuration()
    (tmp_path / "routing_config.yaml").write_text(ROUTING.format(tag="/models/other"))
    completion = SmithersTurnCompletion(factory, "k", authorized=authorized)
    with pytest.raises(ModelDispatchError) as failure:
        completion(messages=[], tools=[], max_tokens=8, turn=1, deadline=None)
    assert failure.value.cause == "ResolvedTagIdentityMismatch"


def test_live_configuration_follows_the_routing_file(tmp_path: Path) -> None:
    client = WorkflowEditBridgeClient(
        image="sha256:" + "1" * 64, runs_root=tmp_path, factory=_factory(tmp_path), run_label="r"
    )
    before = client.configuration()
    (tmp_path / "routing_config.yaml").write_text(ROUTING.format(tag="/models/other"))
    assert client.configuration() != before
    assert client.authorized_smithers == before["turns"]["smithers"]


class FakeSandbox:
    def __init__(self, workspace: Path, cache: Path, image: str, cell_id: str) -> None:
        self.workspace, self.name = workspace, "fake"
        self.observed = {"user": "1000:1000", "network_mode": "none", "readonly_rootfs": True,
                         "memory_bytes": 1536 << 20, "pids_limit": 128, "nano_cpus": 10**9,
                         "tmpfs": {"/workspace": "size=256m", "/cache": "size=256m"}}

    def execute(self, argv: list[str], *, max_output_bytes: int, input_text: str | None = None,
                timeout_s: float = 120.0) -> ToolOutput:
        target = self.workspace / argv[-1]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(input_text or "")
        return ToolOutput("exit=0\n", 7, False)

    def capture_workspace(self) -> dict[str, int]:
        return {}

    def oom_kills(self) -> int | None:
        return None

    def interrupt(self) -> None:
        pass

    def close(self) -> None:
        pass


def _scripted(cell_key: str) -> Any:
    def turn(*, turn: int, **kwargs: Any) -> ModelTurn:
        call = (
            {"name": "write_file", "arguments": json.dumps({"path": "src/a.ts", "content": "b"})}
            if turn == 1 else
            {"name": "submit_output", "arguments": json.dumps({"summary": "done"})}
        )
        return ModelTurn(
            message={"role": "assistant", "content": None,
                     "tool_calls": [{"id": f"c{turn}", "type": "function", "function": call}]},
            finish_reason="tool_calls", prompt_tokens=5, completion_tokens=2, cost_usd=None,
        )

    return turn


async def test_pier_adapter_settles_a_repository_agent_cell(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "store")
    client = WorkflowEditBridgeClient(
        image="sha256:" + "1" * 64, runs_root=tmp_path / "runs", factory=_factory(tmp_path),
        run_label="r", completion_for=_scripted, sandbox_factory=FakeSandbox,
    )
    adapter = PierAdapter(
        store=store, bridge=client,
        binding=RuntimeBinding(
            runtime_version="t", image_digest=client.image,
            configuration_ref=str(store.publish_json(client.configuration())),
            package_digest="sha256:" + "0" * 64,
        ),
        model_route=LOCAL_ROUTE.model_dump(mode="json"),
        trial_limits=trial_limits(client.limits, 900).model_dump(mode="json"),
        package_layout="repository-agent",
    )
    result = await adapter.run_cell(
        input_value={"task": "Edit a.", "repository": {"src/a.ts": "a", "package.json": "{}"}},
        coordinate=CellCoordinate(subject_id="s", arm_id="mess-00", worker_repeat=0,
                                  realization_ref="sha256:" + "2" * 64),
    )
    assert isinstance(result, WorkerSuccess), getattr(result, "message", result)
    patch = base64.b64decode(json.loads(store.read_bytes(result.output["patch_ref"]))[
        "content_base64"])
    assert b"+b" in patch
    assert result.accounting.coverage == "unavailable"
    assert result.accounting.usage == {"prompt_tokens": 10.0, "completion_tokens": 4.0,
                                       "requests": 2.0}
    trajectory = json.loads(base64.b64decode(json.loads(
        store.read_bytes(result.output["raw_trajectory_ref"]))["content_base64"]))
    instruction = trajectory["messages"][1]["content"]
    assert "/workspace" in instruction and "/submission" not in instruction


async def test_tampering_settles_as_a_typed_failure(tmp_path: Path) -> None:
    def tamper(cell_key: str) -> Any:
        def turn(*, turn: int, **kwargs: Any) -> ModelTurn:
            call = (
                {"name": "write_file", "arguments": json.dumps({"path": "package.json",
                                                                 "content": "{\"x\":1}"})}
                if turn == 1 else
                {"name": "submit_output", "arguments": json.dumps({"summary": "s"})}
            )
            return ModelTurn(
                message={"role": "assistant", "content": None,
                         "tool_calls": [{"id": f"c{turn}", "type": "function", "function": call}]},
                finish_reason="tool_calls", prompt_tokens=1, completion_tokens=1, cost_usd=None,
            )

        return turn

    store = ObjectStore(tmp_path / "store")
    client = WorkflowEditBridgeClient(
        image="sha256:" + "1" * 64, runs_root=tmp_path / "runs", factory=_factory(tmp_path),
        run_label="r", completion_for=tamper, sandbox_factory=FakeSandbox,
    )
    adapter = PierAdapter(
        store=store, bridge=client,
        binding=RuntimeBinding(
            runtime_version="t", image_digest=client.image,
            configuration_ref=str(store.publish_json(client.configuration())),
            package_digest="sha256:" + "0" * 64,
        ),
        model_route=LOCAL_ROUTE.model_dump(mode="json"),
        trial_limits=trial_limits(client.limits, 900).model_dump(mode="json"),
        package_layout="repository-agent",
    )
    result = await adapter.run_cell(
        input_value={"task": "Edit.", "repository": {"src/a.ts": "a", "package.json": "{}"}},
        coordinate=CellCoordinate(subject_id="s", arm_id="mess-00", worker_repeat=0,
                                  realization_ref="sha256:" + "2" * 64),
    )
    assert isinstance(result, WorkerFailure)
    assert result.trace["bridge_outcome"]["cause"] == "tampering"
    assert "rejected_worktree/package.json" in result.trace["artifact_refs"]
