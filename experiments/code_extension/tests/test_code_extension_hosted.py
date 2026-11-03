"""Hosted extension wiring reuses the paid agent without live provider requests."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from code_extension.budget import (
    AttemptAlreadyUsed,
    AttemptJournal,
    BilledResponseError,
    JournaledAgentClient,
)
from code_extension.config import RunConfiguration
from code_extension.fixture import PILOT
from code_extension.run import LaunchRefused, _build, prepare
from code_extension.settings import ExtensionAgentSettings
from code_extension.tests.test_code_extension_run import configuration
from verification_pilot.budget import SpendGate

from assay.canonical import digest_bytes
from assay.pier_protocol import ModelRoute
from assay.store import ObjectStore


def hosted_configuration() -> RunConfiguration:
    value = configuration()
    path = PILOT.parent / "dispatch-handler" / "qualification" / "manifest.json"
    value.update(
        route={"endpoint": "https://openrouter.ai/api/v1",
               "model": "openai/gpt-6-luna", "provider": "azure"},
        profile="openrouter",
        bounds=ExtensionAgentSettings.for_model("openai/gpt-6-luna").model_dump(),
        pricing={"basis": "openrouter-pinned-price-ceilings",
                 "conservative_request_bound_usd": None},
        scenario_qualifications=({"scenario": "dispatch-handler",
                                  "manifest_digest": digest_bytes(path.read_bytes())},),
        image_digest=json.loads(path.read_bytes())["observed_runtime_image_digest"],
    )
    return RunConfiguration.model_validate(value)


def test_hosted_prepare_needs_neither_local_routing_nor_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = hosted_configuration()
    monkeypatch.delenv("CODE_EXTENSION_ROUTING_CONFIG", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(
        "code_extension.bridge.observed_image_digest", lambda _: config.image_digest,
    )

    def forbidden(**_kwargs: Any) -> None:
        pytest.fail("hosted preparation constructed a local backend")

    monkeypatch.setattr("code_extension.run.SmithersFactory", forbidden)
    path = tmp_path / "config.json"
    path.write_bytes(config.canonical_bytes())
    summary = prepare(path, tmp_path / "store")
    assert summary["coverage"]["pricing"] == "provider_price_ceiling"
    with pytest.raises(LaunchRefused, match="OPENROUTER_API_KEY"):
        _build(config, ObjectStore(tmp_path / "store"), live=True, plan_digest=summary["digest"])


def agent(
    tmp_path: Path, respond: Any, *, attempt_cap: str = "0.5",
) -> JournaledAgentClient:
    return JournaledAgentClient(
        api_key="test-key", image="test-image", runs_root=tmp_path,
        model_route=ModelRoute(endpoint="https://openrouter.ai/api/v1",
                               model="openai/gpt-6-luna", provider="azure"),
        transport=httpx.MockTransport(respond),
        spend_gate=SpendGate(Decimal(attempt_cap)), run_gate=SpendGate(Decimal("1")),
        journal=AttemptJournal(tmp_path / "requests.jsonl", "plan", "config"),
        cell_key="cell-1", coordinate="coordinate-1",
    )


def billed(*, cost: float | None = 0.001, provider: str = "Azure") -> httpx.Response:
    usage = {"prompt_tokens": 10, "completion_tokens": 2, "cost": cost}
    return httpx.Response(200, json={
        "model": "openai/gpt-6-luna", "provider": provider, "usage": usage,
        "choices": [{"message": {"role": "assistant", "content": "OK"},
                     "finish_reason": "stop"}],
    })


def test_hosted_request_is_journaled_before_dispatch_and_reconciles(tmp_path: Path) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert client.journal is not None
        assert client.journal.records()[-1]["event"] == "reserved"
        body = json.loads(request.content)
        assert body["provider"]["only"] == ["azure"]
        assert body["provider"]["allow_fallbacks"] is False
        return billed()

    client = agent(tmp_path, respond)
    result = client._openrouter_turn([{"role": "user", "content": "OK"}], client.paid_turn_route)
    assert result.cost_usd == 0.001
    assert client.run_gate is not None and client.spend_gate is not None
    assert client.run_gate.spent_usd == client.spend_gate.spent_usd == Decimal("0.001")
    assert client.journal is not None
    restored = SpendGate(Decimal("1"))
    client.journal.reconcile(restored)
    assert restored.spent_usd == client.run_gate.spent_usd
    duplicate = agent(tmp_path, respond)
    with pytest.raises(AttemptAlreadyUsed):
        duplicate._openrouter_turn([], duplicate.paid_turn_route)


@pytest.mark.parametrize("cost", [None, 0.001])
def test_hosted_identity_failure_keeps_known_or_uncertain_billing(
    tmp_path: Path, cost: float | None,
) -> None:
    client = agent(tmp_path, lambda _: billed(cost=cost, provider="unexpected"))
    with pytest.raises(BilledResponseError, match="provider_identity"):
        client._openrouter_turn([], client.paid_turn_route)
    assert client.journal is not None and client.run_gate is not None
    record = client.journal.records()[-1]
    assert record["cost_usd"] == (None if cost is None else "0.001")
    assert client.run_gate.halt == ("billing_uncertain" if cost is None else None)


def test_attempt_cap_refuses_before_http_and_releases_run_reservation(tmp_path: Path) -> None:
    def forbidden(_request: httpx.Request) -> httpx.Response:
        pytest.fail("attempt cap must refuse before HTTP dispatch")

    client = agent(tmp_path, forbidden, attempt_cap="0.000001")
    with pytest.raises(ValueError, match="budget_exhausted"):
        client._openrouter_turn([], client.paid_turn_route)
    assert client.run_gate is not None and client.journal is not None
    assert client.run_gate.spent_usd == client.run_gate.reserved_usd == 0
    assert client.journal.records()[-1]["status"] == "not_sent"
    restored = SpendGate(Decimal("1"))
    client.journal.reconcile(restored)
    assert restored.spent_usd == restored.requests == 0


def test_hosted_over_bound_response_keeps_the_full_billed_cost(tmp_path: Path) -> None:
    client = agent(tmp_path, lambda _: billed(cost=1.0))
    with pytest.raises(BilledResponseError, match="billing_uncertain"):
        client._openrouter_turn([], client.paid_turn_route)
    assert client.run_gate is not None and client.journal is not None
    assert client.run_gate.spent_usd == Decimal("1.0")
    assert client.run_gate.halt == "billing_uncertain"
    record = client.journal.records()[-1]
    assert record["cost_usd"] == "1.0" and record["status"] == "billing_uncertain"
    restored = SpendGate(Decimal("2"))
    client.journal.reconcile(restored)
    assert restored.spent_usd == Decimal("1.0") and restored.halt == "billing_uncertain"


def test_hosted_bridge_edits_and_seals_candidate_with_the_shared_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from code_extension.fixtures import load_scenario
    from code_extension.probe import SUBMIT, _run_script
    from workflow_edit.tests.test_workflow_edit_bridge import FakeSandbox

    from assay.pier_protocol import CandidateSubmission

    config = hosted_configuration()
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("CODE_EXTENSION_ROUTING_CONFIG", raising=False)
    monkeypatch.setattr(
        "code_extension.bridge.observed_image_digest", lambda _: config.image_digest,
    )
    monkeypatch.setattr(
        "code_extension.probe.observed_image_digest", lambda _: config.image_digest,
    )
    prepared = _build(config, ObjectStore(tmp_path / "store"), live=True, plan_digest="plan")
    fixture = load_scenario("dispatch-handler")
    bridge = prepared.workers["baseline"].bridges[fixture.subject_id]
    assert bridge.factory is None
    bridge.sandbox_factory = FakeSandbox
    changed = fixture.repository["src/domain/run-event.ts"] + "\n// edited\n"
    calls = [
        ("write_file", {"path": "src/domain/run-event.ts", "content": changed}),
        ("submit_output", SUBMIT),
    ]

    def respond(_request: httpx.Request) -> httpx.Response:
        name, arguments = calls.pop(0)
        return httpx.Response(200, json={
            "model": config.route.model, "provider": "Azure",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001},
            "choices": [{"finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None, "tool_calls": [{
                    "id": name, "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }],
            }}],
        })

    monkeypatch.setattr(
        "assay_pier_bridge.agent_loop.RepositoryAgentClient._http_client",
        lambda _: httpx.Client(transport=httpx.MockTransport(respond)),
    )
    result, trajectory, observed, _ = _run_script(bridge, fixture, config.image_digest)
    assert isinstance(result.outcome, CandidateSubmission)
    assert b"// edited" in result.artifacts["candidate.patch"]
    assert not calls and len(trajectory["turns"]) == 1
    assert observed["turns"]["backend"] == "openrouter"
    assert bridge.journal is not None and bridge.spend_gate is not None
    assert sum(row["event"] == "finished" for row in bridge.journal.records()) == 2
    assert bridge.spend_gate.spent_usd == Decimal("0.002")
