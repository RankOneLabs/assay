from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from assay_pier_bridge.provider import (
    CHAT_COMPLETIONS_URL,
    MODEL,
    PROVIDER_NAME,
    GuardedOpenRouterClient,
    GuardedRouteError,
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
                                "arguments": json.dumps({"source": "x = 1"}),
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


def _transport(handler: Any) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _client(handler: Any) -> GuardedOpenRouterClient:
    return GuardedOpenRouterClient(api_key="test-key", transport=_transport(handler))


def test_accepts_the_exact_qualified_route() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == CHAT_COMPLETIONS_URL
        return httpx.Response(200, json=_good_body())

    with _client(handler) as client:
        response = client.complete(system_prompt="sys", user_message="hi")
    assert response.usage.cost_usd == pytest.approx(0.0021)
    assert response.usage.prompt_tokens == 10


def test_fails_closed_on_model_mismatch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_good_body(model="openai/gpt-oss-120b"))

    with _client(handler) as client, pytest.raises(GuardedRouteError, match="identity mismatch"):
        client.complete(system_prompt="sys", user_message="hi")


def test_fails_closed_on_provider_mismatch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_good_body(provider="CoreWeave"))

    with _client(handler) as client, pytest.raises(GuardedRouteError, match="identity mismatch"):
        client.complete(system_prompt="sys", user_message="hi")


def test_fails_closed_on_unknown_top_level_field() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_good_body(unexpected_field="surprise"))

    with _client(handler) as client, pytest.raises(GuardedRouteError, match="unknown top-level"):
        client.complete(system_prompt="sys", user_message="hi")


def test_fails_closed_on_missing_cost() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = _good_body()
        del body["usage"]["cost"]
        return httpx.Response(200, json=body)

    with _client(handler) as client, pytest.raises(GuardedRouteError, match="cost"):
        client.complete(system_prompt="sys", user_message="hi")


def test_fails_closed_on_negative_cost() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = _good_body()
        body["usage"]["cost"] = -1
        return httpx.Response(200, json=body)

    with _client(handler) as client, pytest.raises(GuardedRouteError, match="non-negative"):
        client.complete(system_prompt="sys", user_message="hi")


def test_zero_retries_on_transport_error() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("boom", request=request)

    with _client(handler) as client, pytest.raises(GuardedRouteError, match="transport failure"):
        client.complete(system_prompt="sys", user_message="hi")
    assert calls == 1


def test_second_request_on_same_client_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_good_body())

    with _client(handler) as client:
        client.complete(system_prompt="sys", user_message="hi")
        with pytest.raises(GuardedRouteError, match="exactly one request"):
            client.complete(system_prompt="sys", user_message="hi")


def test_fails_closed_on_non_success_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    with _client(handler) as client, pytest.raises(GuardedRouteError, match="non-success"):
        client.complete(system_prompt="sys", user_message="hi")


def test_rejects_blank_api_key() -> None:
    with pytest.raises(ValueError, match="nonblank"):
        GuardedOpenRouterClient(api_key="   ")


def test_accepts_exactly_one_valid_submit_output_call() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_good_body())

    with _client(handler) as client:
        response = client.complete(system_prompt="sys", user_message="hi")
    assert response.submission.source == "x = 1"
    assert response.submission.call_id == "call_1"


def test_fails_closed_on_wrong_finish_reason() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = _good_body()
        body["choices"][0]["finish_reason"] = "stop"
        return httpx.Response(200, json=body)

    with _client(handler) as client, pytest.raises(GuardedRouteError, match="finish"):
        client.complete(system_prompt="sys", user_message="hi")


def test_fails_closed_on_zero_tool_calls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = _good_body()
        body["choices"][0]["message"]["tool_calls"] = []
        return httpx.Response(200, json=body)

    with _client(handler) as client, pytest.raises(GuardedRouteError, match="exactly one tool"):
        client.complete(system_prompt="sys", user_message="hi")


def test_fails_closed_on_two_tool_calls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = _good_body()
        body["choices"][0]["message"]["tool_calls"].append(
            body["choices"][0]["message"]["tool_calls"][0]
        )
        return httpx.Response(200, json=body)

    with _client(handler) as client, pytest.raises(GuardedRouteError, match="exactly one tool"):
        client.complete(system_prompt="sys", user_message="hi")


def test_fails_closed_on_wrong_tool_name() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = _good_body()
        body["choices"][0]["message"]["tool_calls"][0]["function"]["name"] = "shell"
        return httpx.Response(200, json=body)

    with _client(handler) as client, pytest.raises(GuardedRouteError, match="must invoke"):
        client.complete(system_prompt="sys", user_message="hi")


def test_fails_closed_on_non_json_arguments() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = _good_body()
        body["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = "not json"
        return httpx.Response(200, json=body)

    with _client(handler) as client, pytest.raises(GuardedRouteError, match="not valid JSON"):
        client.complete(system_prompt="sys", user_message="hi")


def test_fails_closed_on_unknown_argument_field() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = _good_body()
        body["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = json.dumps(
            {"source": "x = 1", "extra": "nope"}
        )
        return httpx.Response(200, json=body)

    with _client(handler) as client, pytest.raises(GuardedRouteError, match="unknown field"):
        client.complete(system_prompt="sys", user_message="hi")


def test_fails_closed_on_unknown_nested_tool_call_field() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = _good_body()
        body["choices"][0]["message"]["tool_calls"][0]["surprise"] = "nope"
        return httpx.Response(200, json=body)

    with _client(handler) as client, pytest.raises(GuardedRouteError, match="unknown tool call"):
        client.complete(system_prompt="sys", user_message="hi")


def test_fails_closed_on_unknown_message_field() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = _good_body()
        body["choices"][0]["message"]["surprise"] = "nope"
        return httpx.Response(200, json=body)

    with _client(handler) as client, pytest.raises(GuardedRouteError, match="unknown message"):
        client.complete(system_prompt="sys", user_message="hi")


def test_fails_closed_on_oversized_response_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = _good_body()
        body["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = json.dumps(
            {"source": "x" * 200_000}
        )
        return httpx.Response(200, json=body)

    with _client(handler) as client, pytest.raises(GuardedRouteError, match="byte limit"):
        client.complete(system_prompt="sys", user_message="hi")
