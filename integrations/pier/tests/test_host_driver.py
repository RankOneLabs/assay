"""Proves the host-side trial client can run a full trial with the container's
own network permanently at --network none — see host_driver.py's module
docstring for why that split exists."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from assay_pier_bridge.host_driver import (
    GuardedCompletionTrialClient,
    GuardedCompletionTrialHandle,
)
from assay_pier_bridge.identity import package_digest
from assay_pier_bridge.protocol import ModelRoute, TrialLimits, TrialRequest
from assay_pier_bridge.provider import MODEL, PROVIDER_NAME, GuardedOpenRouterClient
from assay_pier_bridge.runtime import BridgeRuntime

ROUTE = ModelRoute(
    endpoint="https://openrouter.ai/api/v1",
    model="anthropic/claude-3-haiku",
    provider="amazon-bedrock",
)
PACKAGE = {"instruction.md": "# Task\n\nsay hi\n"}


def _request(package: dict[str, str] = PACKAGE) -> TrialRequest:
    return TrialRequest(
        cell_id="s1:a1:w0",
        package_digest=package_digest(package),
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
    assert result.usage is not None
    assert result.usage.prompt_tokens == 10
    assert result.usage.completion_tokens == 5
    assert result.usage.cost_usd == 0.0021
    assert result.usage.requests == 1
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

    with pytest.raises(ValueError, match="nonblank"):
        runtime.run_cell(_request({}))


def test_mismatched_package_is_rejected_before_directory_creation(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    client = GuardedCompletionTrialClient(
        package=PACKAGE, api_key="test-key", runs_root=runs_root, system_prompt="sys"
    )
    mismatched = _request({"instruction.md": "different"})

    with pytest.raises(ValueError, match="package_digest"):
        client.create(mismatched)

    assert not runs_root.exists()


def test_direct_handle_construction_rejects_a_mismatched_package(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="package_digest"):
        GuardedCompletionTrialHandle(
            request=_request({"instruction.md": "different"}),
            package=PACKAGE,
            api_key="test-key",
            submission_dir=tmp_path / "submission",
            system_prompt="sys",
        )


def test_handle_uses_the_package_snapshot_taken_at_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = dict(PACKAGE)
    seen: list[str] = []

    def fake_run_one_cell(**kwargs: Any) -> Any:
        from assay_pier_bridge.provider import RouteResponse, RouteUsage, SubmittedOutput

        seen.append(kwargs["instruction"])
        output = kwargs["submission_output"]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("answer = 42", encoding="utf-8")
        return RouteResponse(
            message={},
            usage=RouteUsage(prompt_tokens=1, completion_tokens=1, cost_usd=0.0),
            submission=SubmittedOutput(call_id="call", source="answer = 42"),
            request_bytes=1,
        )

    monkeypatch.setattr("assay_pier_bridge.host_driver.run_one_cell", fake_run_one_cell)
    handle = GuardedCompletionTrialClient(
        package=package, api_key="test-key", runs_root=tmp_path, system_prompt="sys"
    ).create(_request(package))
    package["instruction.md"] = "mutated"

    result = handle.run()

    assert result.status == "succeeded"
    assert seen == [PACKAGE["instruction.md"]]
