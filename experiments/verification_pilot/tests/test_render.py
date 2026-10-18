"""The two placements carry identical handoff bytes and replayable calls."""

from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from workflow_edit import bridge

from assay.adapters.smithers import SmithersFactory
from verification_pilot.analysis import result_tables
from verification_pilot.arms import arm
from verification_pilot.migrations import MIGRATIONS
from verification_pilot.prompts import (
    JOINT_FINAL_MESSAGE,
    PILOT_SYSTEM_PROMPT,
    T1_MESSAGE,
    task_prompt,
)
from verification_pilot.render import (
    block_text,
    render_prefix,
    render_study_pages,
    request_messages,
)
from verification_pilot.session import ContributorBlock, contributor_blocks, rotated_blocks

agent_loop = importlib.import_module("assay_pier_bridge.agent_loop")


def test_study_pages_are_generated_from_analysis_fixture() -> None:
    from verification_pilot.analysis import MeasureCell
    from verification_pilot.observations import Measured, TurnMeasure

    root = Path(__file__).resolve().parents[3]
    pending = render_study_pages(result_tables(()))
    assert pending[0] == (root / "studies/verification-pilot/README.md").read_text()
    assert pending[1] == (root / "studies/verification-pilot/supporting-data.md").read_text()
    measures = (TurnMeasure("T1", "inspection", "first_inspection_is_wide_search",
                            Measured("measured", True)),
                TurnMeasure("T1", "inspection", "ownership_gap", Measured("measured", 1)),
                TurnMeasure("T1", "inspection", "remnant_path_inspected",
                            Measured("measured", True)))
    fixture = result_tables((MeasureCell("fixture", "s1", "rename", "group_a",
                                         "t1-native", measures),))
    main, supporting = render_study_pages(fixture)
    assert "| fixture | 1/1 (100.0%) | pending (0 observed) | qualification pending |" in main
    assert "| fixture | 1/16 | pending | 0 | pending | 0/4 | pending |" in supporting


def test_placements_carry_identical_block_text() -> None:
    for migration in MIGRATIONS:
        blocks = contributor_blocks(migration)
        for rotation in range(3):
            ordered = rotated_blocks(blocks, rotation)
            for route in ("smithers-local", "openrouter"):
                native = render_prefix(ordered, arm("native-template", route))
                quoted = render_prefix(ordered, arm("quoted-template", route))
                native_text = "\n\n".join(
                    message["content"] for message in native if message["role"] == "tool"
                )
                quoted_text = quoted[0]["content"].removeprefix("Quoted contributor handoff:\n")
                assert native_text.encode() == quoted_text.encode() == block_text(ordered).encode()


def test_native_tool_exchanges_replay_unchanged() -> None:
    for migration in MIGRATIONS:
        for rotation in range(3):
            prefix = render_prefix(
                rotated_blocks(contributor_blocks(migration), rotation),
                arm("native-template", "smithers-local"),
            )
            for call_message, result in zip(prefix[::2], prefix[1::2], strict=False):
                if call_message["role"] != "assistant":
                    break
                call = call_message["tool_calls"][0]
                assert agent_loop._replayable_call(call) == call
                assert result == {
                    "role": "tool", "tool_call_id": call["id"], "content": result["content"]
                }
                assert json.loads(call["function"]["arguments"])["path"] in migration.use_sites


def test_request_messages_keep_order_and_pilot_prompt() -> None:
    migration = MIGRATIONS[0]
    blocks = contributor_blocks(migration)
    for placement in ("native-template", "quoted-template"):
        selected = arm(placement, "smithers-local")
        messages = request_messages(task_prompt(migration), blocks, selected)
        assert messages[:2] == [
            {"role": "system", "content": selected.system_prompt},
            {"role": "user", "content": task_prompt(migration)},
        ]
        assert messages[-1] == {
            "role": "user", "content": f"{JOINT_FINAL_MESSAGE}\n\n{T1_MESSAGE}"
        }
        assert "honestly" in selected.system_prompt
        assert "joint-final-and-T1-combined-user-message" in selected.conditions
        placement_condition = (
            "native-contributor-blocks-as-tool-results"
            if placement == "native-template"
            else "quoted-rotation-in-one-user-message"
        )
        other_condition = (
            "quoted-rotation-in-one-user-message"
            if placement == "native-template"
            else "native-contributor-blocks-as-tool-results"
        )
        assert placement_condition in selected.conditions
        assert other_condition not in selected.conditions


@pytest.mark.parametrize("placement", ["native-template", "quoted-template"])
def test_openrouter_serialized_request_body_is_exact(
    placement: str, tmp_path: Path
) -> None:
    from assay_pier_bridge.agent_loop import RepositoryAgentClient
    from assay_pier_bridge.protocol import ModelRoute

    block = ContributorBlock("group_a", ("src/a.ts",), "A")
    selected = arm(placement, "openrouter")  # type: ignore[arg-type]
    messages = request_messages("Verify.", (block,), selected)
    expected_prefix: list[dict[str, Any]]
    if placement == "native-template":
        expected_prefix = [
            {"role": "assistant", "content": None, "tool_calls": [{
                "id": "pilot-contributor-1", "type": "function",
                "function": {"name": "read_file", "arguments": '{"path":"src/a.ts"}'},
            }]},
            {"role": "tool", "tool_call_id": "pilot-contributor-1", "content": "A"},
        ]
    else:
        expected_prefix = [{"role": "user", "content": "Quoted contributor handoff:\nA"}]
    expected_messages = [
        {"role": "system", "content": PILOT_SYSTEM_PROMPT},
        {"role": "user", "content": "Verify."},
        *expected_prefix,
        {"role": "user", "content": f"{JOINT_FINAL_MESSAGE}\n\n{T1_MESSAGE}"},
    ]
    assert messages == expected_messages
    captured: list[bytes] = []

    def respond(request: httpx.Request) -> httpx.Response:
        captured.append(request.content)
        return httpx.Response(400)

    client = RepositoryAgentClient(
        api_key="test-key", image="test-image", runs_root=tmp_path,
        model_route=ModelRoute(), transport=httpx.MockTransport(respond),
    )
    with pytest.raises(ValueError, match="provider_response"):
        client._openrouter_turn(messages)
    expected_body = {
        "model": "anthropic/claude-3-haiku", "messages": expected_messages,
        "tools": client.tools, "tool_choice": "auto", "max_tokens": 8192,
        "stream": False,
        "provider": {
            "data_collection": "deny", "zdr": True,
            "only": ["amazon-bedrock"], "order": ["amazon-bedrock"],
            "allow_fallbacks": False, "require_parameters": True,
            "max_price": {"prompt": 0.25, "completion": 1.25, "request": 0},
        },
    }
    assert captured == [json.dumps(expected_body, separators=(",", ":")).encode()]


def test_openrouter_native_rotation_serializes_all_tool_exchanges(
    tmp_path: Path,
) -> None:
    from assay_pier_bridge.agent_loop import RepositoryAgentClient
    from assay_pier_bridge.protocol import ModelRoute

    blocks = rotated_blocks(contributor_blocks(MIGRATIONS[2]), 1)
    messages = request_messages("Verify.", blocks, arm("native-template", "openrouter"))
    expected_blocks = tuple((block.paths[0], block.text) for block in blocks)
    expected_messages: list[dict[str, Any]] = [
        {"role": "system", "content": PILOT_SYSTEM_PROMPT},
        {"role": "user", "content": "Verify."},
    ]
    for index, (path, content) in enumerate(expected_blocks, start=1):
        call_id = f"pilot-contributor-{index}"
        expected_messages.extend((
            {"role": "assistant", "content": None, "tool_calls": [{
                "id": call_id, "type": "function",
                "function": {"name": "read_file", "arguments": f'{{"path":"{path}"}}'},
            }]},
            {"role": "tool", "tool_call_id": call_id, "content": content},
        ))
    expected_messages.append({
        "role": "user", "content": f"{JOINT_FINAL_MESSAGE}\n\n{T1_MESSAGE}",
    })
    captured: list[bytes] = []

    def respond(request: httpx.Request) -> httpx.Response:
        captured.append(request.content)
        return httpx.Response(400)

    client = RepositoryAgentClient(
        api_key="test-key", image="test-image", runs_root=tmp_path,
        model_route=ModelRoute(), transport=httpx.MockTransport(respond),
    )
    with pytest.raises(ValueError, match="provider_response"):
        client._openrouter_turn(messages)
    expected_body = {
        "model": "anthropic/claude-3-haiku", "messages": expected_messages,
        "tools": client.tools, "tool_choice": "auto", "max_tokens": 8192,
        "stream": False,
        "provider": {
            "data_collection": "deny", "zdr": True,
            "only": ["amazon-bedrock"], "order": ["amazon-bedrock"],
            "allow_fallbacks": False, "require_parameters": True,
            "max_price": {"prompt": 0.25, "completion": 1.25, "request": 0},
        },
    }
    assert captured == [json.dumps(expected_body, separators=(",", ":")).encode()]


@pytest.mark.parametrize("placement", ["native-template", "quoted-template"])
def test_smithers_serialized_request_body_is_exact(
    placement: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    block = ContributorBlock("group_a", ("src/a.ts",), "A")
    selected = arm(placement, "smithers-local")  # type: ignore[arg-type]
    messages = request_messages("Verify.", (block,), selected)
    routing = tmp_path / "routing.yaml"
    routing.write_text(
        "machines:\n  mcbain:\n    backend: vllm\n"
        "models:\n  qwen-coder-32b:\n    machines: [mcbain]\n"
        "    backend_tags:\n      vllm: /models/coder\n"
    )
    factory = SmithersFactory(
        model="qwen-coder-32b", machine="mcbain", routing_config=routing,
        dispatch_url="http://smithers.test", poll_interval=0,
    )
    created = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)
    captured: list[bytes] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.host == "mcbain":
            return httpx.Response(200, json={
                "job_id": "job-1", "status": "complete",
                "usage": {"model": "/models/coder", "input_tokens": 1, "output_tokens": 1},
            })
        if request.method == "POST":
            captured.append(request.content)
            return httpx.Response(200, json={"job_id": "job-1"})
        return httpx.Response(200, json={
            "job_id": "job-1", "status": "complete", "model": "qwen-coder-32b",
            "machine": "mcbain", "created_at": created.isoformat(),
            "started_at": (created + timedelta(seconds=1)).isoformat(),
            "completed_at": (created + timedelta(seconds=2)).isoformat(),
            "result": {"content": "", "tool_calls": []},
        })

    original_init = httpx.AsyncClient.__init__

    def patched(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> None:
        kwargs["transport"] = httpx.MockTransport(respond)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)
    completion = bridge.SmithersTurnCompletion(factory, "cell-key")
    completion(messages=messages, tools=[], max_tokens=512, turn=1, deadline=None)
    expected_body = {
        "task_type": "inference",
        "payload": {
            "messages": messages, "tools": [], "tool_choice": "required",
            "max_tokens": 512, "temperature": 0.7,
        },
        "requester": factory.requester, "model": "qwen-coder-32b",
        "machine": "mcbain", "timeout_seconds": factory.timeout_seconds,
        "max_retries": 0, "idempotency_key": "cell-key:t1",
    }
    assert captured == [json.dumps(expected_body, separators=(",", ":")).encode()]
