from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from assay_pier_bridge.__main__ import run_one_cell
from assay_pier_bridge.provider import (
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


def test_run_one_cell_writes_the_submitted_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_good_body())

    monkeypatch.setattr(
        "assay_pier_bridge.__main__.GuardedOpenRouterClient",
        lambda **kwargs: GuardedOpenRouterClient(
            api_key=kwargs["api_key"], transport=httpx.MockTransport(handler)
        ),
    )
    output = tmp_path / "submission" / "output"

    source = run_one_cell(
        instruction="do the thing",
        system_prompt="sys",
        api_key="test-key",
        submission_output=output,
    )

    assert source == "answer = 42"
    assert output.read_text(encoding="utf-8") == "answer = 42"


def test_run_one_cell_propagates_a_guarded_route_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_good_body(model="wrong/model"))

    monkeypatch.setattr(
        "assay_pier_bridge.__main__.GuardedOpenRouterClient",
        lambda **kwargs: GuardedOpenRouterClient(
            api_key=kwargs["api_key"], transport=httpx.MockTransport(handler)
        ),
    )
    output = tmp_path / "submission" / "output"

    with pytest.raises(GuardedRouteError):
        run_one_cell(
            instruction="do the thing",
            system_prompt="sys",
            api_key="test-key",
            submission_output=output,
        )
    assert not output.exists()
