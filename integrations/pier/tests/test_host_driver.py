"""Proves the host-side trial client can run a full trial with the container's
own network permanently at --network none — see host_driver.py's module
docstring for why that split exists."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from assay_pier_bridge.host_driver import GuardedCompletionTrialClient
from assay_pier_bridge.protocol import ModelRoute, TrialLimits, TrialRequest
from assay_pier_bridge.provider import MODEL, PROVIDER_NAME, GuardedOpenRouterClient
from assay_pier_bridge.runtime import BridgeRuntime

ROUTE = ModelRoute(
    endpoint="https://openrouter.ai/api/v1",
    model="anthropic/claude-3-haiku",
    provider="amazon-bedrock",
)
PACKAGE = {"instruction.md": "# Task\n\nsay hi\n"}


def _request() -> TrialRequest:
    return TrialRequest(
        cell_id="s1:a1:w0",
        package_digest="sha256:" + "0" * 64,
        model_route=ROUTE,
        limits=TrialLimits(cpu=1, memory_mb=256, pids=32, timeout_s=20, storage_mb=64),
    )


def _good_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": "gen-abc123",
        "model": MODEL,
        "provider": PROVIDER_NAME,
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "submit_output",
                                "arguments": json.dumps({"source": "answer = 42"}),
                            },
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0021},
    }
    body.update(overrides)
    return body


def test_a_trial_succeeds_with_the_container_network_permanently_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of the host-side client: no --network flag exists
    anywhere in this path, yet the guarded call still completes."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_good_body())

    monkeypatch.setattr(
        "assay_pier_bridge.__main__.GuardedOpenRouterClient",
        lambda **kwargs: GuardedOpenRouterClient(
            api_key=kwargs["api_key"], transport=httpx.MockTransport(handler)
        ),
    )
    client = GuardedCompletionTrialClient(
        package=PACKAGE, api_key="test-key", runs_root=tmp_path, system_prompt="sys"
    )
    runtime = BridgeRuntime(client)

    result = runtime.run_cell(_request())

    assert result.status == "succeeded"
    assert result.submission_ref is not None
    assert result.effective.network_policy == "host-process-guarded-route-only"
    assert result.effective.containers_remaining == 0
    assert result.effective.teardown_completed is True


def test_a_missing_instruction_fails_the_trial_without_a_network_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no network call should happen without an instruction")

    monkeypatch.setattr(
        "assay_pier_bridge.__main__.GuardedOpenRouterClient",
        lambda **kwargs: GuardedOpenRouterClient(
            api_key=kwargs["api_key"], transport=httpx.MockTransport(handler)
        ),
    )
    client = GuardedCompletionTrialClient(
        package={}, api_key="test-key", runs_root=tmp_path, system_prompt="sys"
    )
    runtime = BridgeRuntime(client)

    result = runtime.run_cell(_request())

    assert result.status == "failed"
    assert result.submission_ref is None
