"""The paid route's operator dollar cap reserves before dispatch and settles after."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from verification_pilot.budget import (
    HAIKU_TURN_ROUTE,
    PROMPT_TOKEN_SLACK,
    BudgetedAgentClient,
    SpendGate,
    request_cost_bound,
)

MESSAGES = [{"role": "system", "content": "s"}, {"role": "user", "content": "Verify."}]


def _client(tmp_path: Path, gate: SpendGate,
            respond: Any) -> BudgetedAgentClient:
    from assay_pier_bridge.protocol import ModelRoute

    return BudgetedAgentClient(api_key="test-key", image="test-image", runs_root=tmp_path,
                               model_route=ModelRoute(), transport=httpx.MockTransport(respond),
                               spend_gate=gate)


def _billed(cost: float | None) -> httpx.Response:
    usage: dict[str, Any] = {"prompt_tokens": 10, "completion_tokens": 2}
    if cost is not None:
        usage["cost"] = cost
    return httpx.Response(200, json={
        "model": "anthropic/claude-3-haiku", "provider": "Amazon Bedrock",
        "choices": [{"message": {"role": "assistant", "content": "ok"},
                     "finish_reason": "stop"}],
        "usage": usage,
    })


def test_bound_prices_request_bytes_and_max_output_at_max_price() -> None:
    bound = request_cost_bound(HAIKU_TURN_ROUTE, request_bytes=1_000, max_output_tokens=8_192)
    assert bound == (Decimal(1_000 + PROMPT_TOKEN_SLACK) * Decimal("0.25")
                     + Decimal(8_192) * Decimal("1.25")) / Decimal(1_000_000)


def test_gate_refuses_a_request_the_remaining_cap_cannot_cover() -> None:
    gate = SpendGate(Decimal("0.02"))
    gate.reserve(Decimal("0.015"))
    gate.settle(Decimal("0.015"), 0.005)
    with pytest.raises(ValueError, match="budget_exhausted"):
        gate.reserve(Decimal("0.016"))
    assert gate.halt == "budget_exhausted"
    assert gate.spent_usd == Decimal("0.005")
    with pytest.raises(ValueError, match="budget_exhausted"):
        gate.reserve(Decimal("0.001"))


@pytest.mark.parametrize("cost", [None, 1.0])
def test_unknown_or_overbound_cost_halts_billing_uncertain(cost: float | None) -> None:
    gate = SpendGate(Decimal("5"))
    gate.reserve(Decimal("0.5"))
    gate.settle(Decimal("0.5"), cost)
    assert gate.halt == "billing_uncertain"
    assert gate.spent_usd == (Decimal("0.5") if cost is None else Decimal("1.0"))


def test_gate_rejects_a_nonpositive_cap() -> None:
    with pytest.raises(ValueError, match="positive"):
        SpendGate(Decimal(0))


def test_budgeted_turn_settles_to_the_billed_cost(tmp_path: Path) -> None:
    gate = SpendGate(Decimal("1"))
    client = _client(tmp_path, gate, lambda request: _billed(0.0003))
    turn = client._openrouter_turn(MESSAGES)
    assert turn.cost_usd == 0.0003
    assert gate.spent_usd == Decimal("0.0003")
    assert gate.reserved_usd == 0
    assert gate.requests == 1
    assert gate.halt is None


def test_response_billed_above_its_reservation_stops_the_cell(tmp_path: Path) -> None:
    gate = SpendGate(Decimal("5"))
    client = _client(tmp_path, gate, lambda request: _billed(2.0))
    with pytest.raises(ValueError, match="billing_uncertain"):
        client._openrouter_turn(MESSAGES)
    assert gate.halt == "billing_uncertain"
    assert gate.spent_usd == Decimal("2.0")
    assert gate.reserved_usd == 0


def test_request_over_the_cap_is_never_sent(tmp_path: Path) -> None:
    sent: list[bytes] = []

    def respond(request: httpx.Request) -> httpx.Response:
        sent.append(request.content)
        return _billed(0.0)

    gate = SpendGate(Decimal("0.001"))
    client = _client(tmp_path, gate, respond)
    with pytest.raises(ValueError, match="budget_exhausted"):
        client._openrouter_turn(MESSAGES)
    assert sent == []
    assert gate.spent_usd == 0
    assert gate.requests == 0


def test_reservation_covers_the_serialized_request(tmp_path: Path) -> None:
    sent: list[bytes] = []

    def respond(request: httpx.Request) -> httpx.Response:
        sent.append(request.content)
        return _billed(0.0)

    gate = SpendGate(Decimal("1"))
    client = _client(tmp_path, gate, respond)
    reserved: list[Decimal] = []
    reserve = gate.reserve

    def spy(bound: Decimal) -> None:
        reserved.append(bound)
        reserve(bound)

    gate.reserve = spy  # type: ignore[method-assign]
    client._openrouter_turn(MESSAGES)
    body = json.loads(sent[0])
    # Every byte actually sent is priced as a prompt token, with no slack left over.
    every_sent_byte = (Decimal(len(sent[0])) * Decimal("0.25")
                       + Decimal(body["max_tokens"]) * Decimal("1.25")) / Decimal(1_000_000)
    assert reserved[0] >= every_sent_byte


def test_dispatched_request_without_billing_halts(tmp_path: Path) -> None:
    gate = SpendGate(Decimal("1"))
    client = _client(tmp_path, gate, lambda request: httpx.Response(500))
    with pytest.raises(ValueError, match="provider_response"):
        client._openrouter_turn(MESSAGES)
    assert gate.halt == "billing_uncertain"
    assert gate.spent_usd > 0
    with pytest.raises(ValueError, match="billing_uncertain"):
        client._openrouter_turn(MESSAGES)


def test_local_route_takes_no_spend_gate(tmp_path: Path) -> None:
    from assay_pier_bridge.protocol import ModelRoute

    from verification_pilot.bridge import create_pilot_agent
    from verification_pilot.inputs import T2_TEXT, T3_TEXT
    from verification_pilot.settings import VerificationPilotSettings

    with pytest.raises(ValueError, match="no spend gate"):
        create_pilot_agent(
            settings=VerificationPilotSettings(), image="test-image", runs_root=tmp_path,
            model_route=ModelRoute(endpoint="http://willie:8900", model="qwen-coder-32b",
                                   provider="smithers-local"),
            completion=lambda **_: None,  # type: ignore[arg-type,return-value]
            next_user_turns=(T2_TEXT, T3_TEXT), spend_gate=SpendGate(Decimal("1")),
        )
