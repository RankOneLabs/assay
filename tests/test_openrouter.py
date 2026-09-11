from __future__ import annotations

import asyncio
import copy
import dataclasses
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import paa_contracts
import pytest
from jig.core.types import CompletionParams, LLMResponse, Message, Role

from assay.adapters.consistency import CompletionNotSent, ConsistencyWorker
from assay.adapters.openrouter import ENDPOINT, QWEN_NOVITA, OpenRouterFactory, source_output_tool
from assay.canonical import canonical_json
from assay.execution import WorkerFailure, WorkerSuccess
from assay.investigations.consistency import TASKS
from assay.investigations.openrouter_smoke import qwen_smoke_settings
from assay.investigations.pilot import (
    PilotFailed,
    PilotPrepared,
    PilotSucceeded,
    prepare_pilot,
    run_pilot,
)
from assay.models import StudySnapshot
from assay.store import ObjectStore
from assay.verify import verify_bundle


def response_payload(source: str = TASKS[0].reused_source) -> dict[str, Any]:
    return {
        "id": "gen-fake-only",
        "object": "chat.completion",
        "created": 1,
        "model": QWEN_NOVITA.model,
        "provider": "Novita",
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "submission",
                            "type": "function",
                            "function": {
                                "name": "submit_output",
                                "arguments": json.dumps({"source": source}),
                            },
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "cost": 0.0000205},
    }


def params() -> CompletionParams:
    return CompletionParams(
        messages=[Message(Role.USER, "write a function")],
        system="test system",
        tools=[source_output_tool()],
        temperature=0,
        max_tokens=2048,
    )


class Wire:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.transports: set[int] = set()
        self.closed: set[int] = set()
        self.payload: Any = response_payload()
        self.status = 200
        self.error: Exception | None = None
        self.dynamic = False
        self.block = False
        self.started = asyncio.Event()


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> Wire:
    """Intercept at the HTTP transport, keeping the real SDK and Jig parser."""
    state = Wire()
    original_close = httpx.AsyncHTTPTransport.aclose

    async def send(transport: httpx.AsyncHTTPTransport, request: httpx.Request) -> httpx.Response:
        state.requests.append(request)
        state.transports.add(id(transport))
        state.started.set()
        if state.block:
            await asyncio.Event().wait()
        if state.error:
            raise state.error
        payload = state.payload
        if state.dynamic:
            body = json.loads(request.content)
            prompt = json.loads(next(m["content"] for m in body["messages"] if m["role"] == "user"))
            task = next(t for t in TASKS if t.instruction == prompt["instruction"])
            payload = response_payload(task.reused_source)
        return httpx.Response(state.status, content=json.dumps(payload), request=request)

    async def close(transport: httpx.AsyncHTTPTransport) -> None:
        state.closed.add(id(transport))
        await original_close(transport)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", send)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "aclose", close)
    monkeypatch.delenv("OPENAI_CUSTOM_HEADERS", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    return state


def factory() -> OpenRouterFactory:
    return OpenRouterFactory(api_key="test-secret-not-a-real-key")


def realization() -> dict[str, Any]:
    return {
        "task": TASKS[0].model_dump(),
        "repository": {"module.py": TASKS[0].helper_source},
        "base_subject_ref": "sha256:" + "0" * 64,
    }


def test_configuration_is_detached_and_secret_free(wire: Wire) -> None:
    owner = factory()
    declared = canonical_json(owner.configuration())
    changed = owner.configuration()
    changed["routing"]["only"].append("another-provider")
    assert canonical_json(owner.configuration()) == declared
    assert b"test-secret" not in declared and "test-secret" not in repr(owner)
    assert not wire.requests


@pytest.mark.asyncio
async def test_real_sdk_request_routing_limits_usage_and_cleanup(wire: Wire) -> None:
    owner = factory()
    clients = [owner.create(), owner.create()]
    original = params()
    before = copy.deepcopy(original)
    try:
        for client in clients:
            assert client.configuration() == owner.configuration()
            result = await client.complete(original)
            assert isinstance(result, LLMResponse)
            assert result.usage.cost == 0.0000205
            assert result.usage.input_tokens == 100 and result.usage.output_tokens == 50
            assert result.tool_calls[0].arguments == {"source": TASKS[0].reused_source}
    finally:
        for client in clients:
            await client.aclose()
            await client.aclose()
    assert original == before
    assert len(wire.requests) == len(wire.transports) == 2
    assert wire.closed == wire.transports
    for request in wire.requests:
        assert str(request.url) == ENDPOINT + "/chat/completions"
        assert request.headers["authorization"] == "Bearer test-secret-not-a-real-key"
        body = json.loads(request.content)
        assert body["provider"] == QWEN_NOVITA.routing()
        assert body["provider"]["data_collection"] == "deny"
        assert body["provider"]["zdr"] is True
        assert body["model"] == QWEN_NOVITA.model
        assert body["max_tokens"] == 2048 and body["temperature"] == 0
        assert body["tool_choice"] == {"type": "function", "function": {"name": "submit_output"}}
        assert body["transforms"] == body["plugins"] == []
        assert body["stream"] is False
        assert "models" not in body and "reasoning" not in body


@pytest.mark.parametrize("status", [302, 400, 401, 408, 429, 500, 503])
@pytest.mark.asyncio
async def test_http_errors_are_not_retried_or_leaked(wire: Wire, status: int) -> None:
    wire.status = status
    wire.payload = {"error": {"message": "sensitive-provider-error-body"}}
    result = await ConsistencyWorker(factory(), qwen_smoke_settings(), allow_paid=True).run(
        input_value=realization(), arm_id="clean"
    )
    assert isinstance(result, WorkerFailure)
    assert len(wire.requests) == 1
    assert wire.closed == wire.transports
    assert result.accounting.coverage == "unavailable"
    assert result.trace["billing_uncertain"]
    assert "sensitive-provider-error-body" not in repr(result)
    assert "test-secret" not in repr(result)


@pytest.mark.parametrize("error", [httpx.ConnectError("secret"), httpx.ReadTimeout("secret")])
@pytest.mark.asyncio
async def test_transport_errors_are_not_retried(wire: Wire, error: Exception) -> None:
    wire.error = error
    result = await ConsistencyWorker(factory(), qwen_smoke_settings(), allow_paid=True).run(
        input_value=realization(), arm_id="clean"
    )
    assert isinstance(result, WorkerFailure)
    assert len(wire.requests) == 1 and wire.closed == wire.transports
    assert "secret" not in repr(result)


@pytest.mark.parametrize("field", ["prompt_tokens", "completion_tokens", "cost"])
@pytest.mark.parametrize("value", [None, True, "1", -1, float("nan"), float("inf")])
@pytest.mark.asyncio
async def test_raw_usage_rejected_before_sdk_coercion(wire: Wire, field: str, value: Any) -> None:
    wire.payload["usage"][field] = value
    worker = ConsistencyWorker(factory(), qwen_smoke_settings(), allow_paid=True)
    for index in range(2):
        result = await worker.run(input_value=realization(), arm_id="clean")
        assert isinstance(result, WorkerFailure)
        assert result.error_type == ("InvalidUsage" if index == 0 else "BudgetHalted")
        assert result.accounting.coverage == "unavailable"
    assert len(wire.requests) == 1  # Uncertain billing halts subsequent attempts.


@pytest.mark.parametrize(
    "mutation", ["model", "provider", "usage", "missing_cost", "empty_choices"]
)
@pytest.mark.asyncio
async def test_incomplete_or_mismatched_responses_fail(wire: Wire, mutation: str) -> None:
    if mutation == "missing_cost":
        del wire.payload["usage"]["cost"]
    elif mutation == "empty_choices":
        wire.payload["choices"] = []
    else:
        wire.payload[mutation] = None
    result = await ConsistencyWorker(factory(), qwen_smoke_settings(), allow_paid=True).run(
        input_value=realization(), arm_id="clean"
    )
    assert isinstance(result, WorkerFailure)
    assert result.accounting.coverage == "unavailable" and len(wire.requests) == 1


@pytest.mark.parametrize(
    "update",
    [
        {"provider_params": {"extra_body": {"provider": {"allow_fallbacks": True}}}},
        {"provider_params": {"max_tokens": 100000}},
        {"reasoning": True},
        {"response_format": {"type": "json_object"}},
        {"max_tokens": 2049},
        {"max_tokens": None},
        {"max_tokens": True},
        {"tools": []},
    ],
)
@pytest.mark.asyncio
async def test_completion_overrides_fail_before_http(wire: Wire, update: dict[str, Any]) -> None:
    client = factory().create()
    try:
        with pytest.raises(Exception, match="unsupported source-pilot"):
            await client.complete(dataclasses.replace(params(), **update))
    finally:
        await client.aclose()
    assert not wire.requests


@pytest.mark.asyncio
async def test_request_body_byte_bound_includes_system_schema_and_history(wire: Wire) -> None:
    owner = OpenRouterFactory(
        QWEN_NOVITA.model_copy(update={"max_request_body_bytes": 1000}), "test-key"
    )
    client = owner.create()
    try:
        with pytest.raises(Exception, match="byte limit"):
            await client.complete(dataclasses.replace(params(), system="x" * 1001))
    finally:
        await client.aclose()
    assert not wire.requests


@pytest.mark.asyncio
async def test_external_cancellation_closes_transport(wire: Wire) -> None:
    wire.block = True
    worker = ConsistencyWorker(factory(), qwen_smoke_settings(), allow_paid=True)
    task = asyncio.create_task(worker.run(input_value=realization(), arm_id="clean"))
    await wire.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert wire.closed == wire.transports
    second = await worker.run(input_value=realization(), arm_id="inconsistent")
    assert isinstance(second, WorkerFailure) and len(wire.requests) == 1


def test_credentials_are_required_only_when_creating_clients(wire: Wire) -> None:
    owner = OpenRouterFactory()
    assert owner.configuration()["model"] == QWEN_NOVITA.model
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        owner.create()
    assert not wire.requests


def test_custom_sdk_headers_rejected(wire: Wire, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_CUSTOM_HEADERS", "x-secret: should-not-be-sent")
    with pytest.raises(ValueError, match="unset OPENAI_CUSTOM_HEADERS"):
        factory().create()
    assert not wire.requests


@pytest.mark.asyncio
async def test_unrelated_sdk_and_proxy_environment_cannot_change_route(
    wire: Wire, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("OPENAI_BASE_URL", "HTTPS_PROXY", "HTTP_PROXY"):
        monkeypatch.setenv(name, "https://wrong.invalid")
    monkeypatch.setenv("OPENAI_API_KEY", "wrong-key")
    monkeypatch.setenv("OPENAI_ORG_ID", "wrong-org")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "wrong-project")
    client = factory().create()
    try:
        await client.complete(params())
    finally:
        await client.aclose()
    request = wire.requests[0]
    assert str(request.url).startswith(ENDPOINT)
    assert request.headers["authorization"] == "Bearer test-secret-not-a-real-key"
    assert "wrong" not in str(request.headers)


@pytest.mark.asyncio
async def test_prepare_paid_gates_and_two_mocked_runs_export_verified_bundles(
    wire: Wire, tmp_path: Path
) -> None:
    store = ObjectStore(tmp_path / "store")
    owner = factory()
    with patch.object(
        OpenRouterFactory, "create", side_effect=AssertionError("prepare created client")
    ):
        prepared = prepare_pilot(
            store,
            factory=OpenRouterFactory(),
            settings=qwen_smoke_settings(),
            schemas={
                name: paa_contracts.load_schema(name)
                for name in ("paa-task", "paa-evidence-record", "paa-operating-record")
            },
        )
    assert isinstance(prepared, PilotPrepared), prepared
    assert prepared.executions == prepared.evaluations == 12
    snapshot = StudySnapshot.model_validate_json(store.read_bytes(prepared.snapshot_ref))
    assert snapshot.arms[0].worker["provider"] == snapshot.arms[1].worker["provider"]
    assert not wire.requests
    denied = await run_pilot(
        store, plan_ref=prepared.plan_ref, authorization=prepared.plan_ref, factory=owner
    )
    assert isinstance(denied, PilotFailed) and not wire.requests
    wrong = await run_pilot(
        store,
        plan_ref=prepared.plan_ref,
        authorization="sha256:" + "0" * 64,
        factory=owner,
        allow_paid=True,
    )
    assert isinstance(wrong, PilotFailed) and not wire.requests
    wire.dynamic = True
    for index in range(2):
        destination = tmp_path / f"bundle-{index}"
        result = await run_pilot(
            store,
            plan_ref=prepared.plan_ref,
            authorization=prepared.plan_ref,
            factory=owner,
            allow_paid=True,
            export_destination=destination,
        )
        assert isinstance(result, PilotSucceeded), result
        assert verify_bundle(ObjectStore(destination), result.report_ref) == ()
        assert len(wire.requests) == (index + 1) * 12
    assert wire.closed == wire.transports


@pytest.mark.asyncio
async def test_source_success_retains_usage_and_no_secrets(wire: Wire) -> None:
    result = await ConsistencyWorker(factory(), qwen_smoke_settings(), allow_paid=True).run(
        input_value=realization(), arm_id="clean"
    )
    assert isinstance(result, WorkerSuccess), result
    assert result.accounting.amount == 0.0000205
    assert result.trace["response_models"] == [QWEN_NOVITA.model]
    assert "test-secret" not in canonical_json(result.trace).decode()


@pytest.mark.parametrize("value", [1.0, 2**53])
@pytest.mark.parametrize("field", ["prompt_tokens", "completion_tokens"])
@pytest.mark.asyncio
async def test_token_usage_requires_exact_safe_integers(wire: Wire, field: str, value: Any) -> None:
    wire.payload["usage"][field] = value
    result = await ConsistencyWorker(factory(), qwen_smoke_settings(), allow_paid=True).run(
        input_value=realization(), arm_id="clean"
    )
    assert isinstance(result, WorkerFailure) and result.error_type == "InvalidUsage"


@pytest.mark.asyncio
async def test_explicit_zero_cost_is_preserved(wire: Wire) -> None:
    wire.payload["usage"]["cost"] = 0
    result = await ConsistencyWorker(factory(), qwen_smoke_settings(), allow_paid=True).run(
        input_value=realization(), arm_id="clean"
    )
    assert isinstance(result, WorkerSuccess)
    assert result.accounting.amount == 0 and result.accounting.coverage == "estimated"


@pytest.mark.asyncio
async def test_cost_bound_violation_halts_later_requests(wire: Wire) -> None:
    wire.payload["usage"]["cost"] = 0.03
    worker = ConsistencyWorker(factory(), qwen_smoke_settings(), allow_paid=True)
    first = await worker.run(input_value=realization(), arm_id="clean")
    second = await worker.run(input_value=realization(), arm_id="clean")
    assert isinstance(first, WorkerFailure) and isinstance(second, WorkerFailure)
    assert first.trace["provider_usage"][0]["cost"] == 0.03
    assert first.accounting.coverage == "unavailable"
    assert second.error_type == "BudgetHalted" and len(wire.requests) == 1


@pytest.mark.asyncio
async def test_runtime_sdk_version_drift_fails_before_provider_calls(
    wire: Wire, tmp_path: Path
) -> None:
    store = ObjectStore(tmp_path)
    prepared = prepare_pilot(
        store,
        factory=factory(),
        settings=qwen_smoke_settings(),
        schemas={
            name: paa_contracts.load_schema(name)
            for name in ("paa-task", "paa-evidence-record", "paa-operating-record")
        },
    )
    assert isinstance(prepared, PilotPrepared)
    with patch("assay.adapters.openrouter.version", return_value="changed"):
        result = await run_pilot(
            store,
            plan_ref=prepared.plan_ref,
            authorization=prepared.plan_ref,
            factory=factory(),
            allow_paid=True,
        )
    assert isinstance(result, PilotFailed) and not wire.requests


def test_source_tool_matches_pinned_jig_and_configuration_is_detached(wire: Wire) -> None:
    from jig.core.runner import _build_submit_output_tool

    from assay.adapters.consistency import SourceOutput

    assert source_output_tool() == _build_submit_output_tool(SourceOutput)
    owner = factory()
    changed = owner.configuration()
    changed["tool_definition"]["parameters"].clear()
    changed["routing"]["zdr"] = False
    assert owner.configuration()["tool_definition"] == dataclasses.asdict(source_output_tool())
    assert owner.configuration()["routing"]["zdr"] is True


@pytest.mark.parametrize(
    "update",
    [
        {"parameters": {}},
        {"parameters": {"type": "object", "properties": {"command": {"type": "string"}}}},
        {"description": "Run a command"},
        {"strict": False},
        {"strict": 1},
        {"identity_fields": ["source"]},
    ],
)
@pytest.mark.asyncio
async def test_changed_submission_definition_is_rejected_before_send(
    wire: Wire, update: dict[str, Any]
) -> None:
    client = factory().create()
    try:
        tool = dataclasses.replace(source_output_tool(), **update)
        result = await client.complete_result(dataclasses.replace(params(), tools=[tool]))
        assert isinstance(result, CompletionNotSent)
    finally:
        await client.aclose()
    assert not wire.requests


@pytest.mark.parametrize("privacy", [{"zdr": False}, {"data_collection": "allow"}])
@pytest.mark.asyncio
async def test_privacy_overrides_are_rejected(wire: Wire, privacy: dict[str, Any]) -> None:
    client = factory().create()
    try:
        result = await client.complete_result(
            dataclasses.replace(params(), provider_params={"extra_body": {"provider": privacy}})
        )
        assert isinstance(result, CompletionNotSent)
    finally:
        await client.aclose()
    assert not wire.requests


@pytest.mark.asyncio
async def test_no_privacy_eligible_route_fails_without_fallback(wire: Wire) -> None:
    wire.status = 404
    wire.payload = {"error": {"message": "No endpoints satisfy privacy requirements"}}
    worker = ConsistencyWorker(factory(), qwen_smoke_settings(), allow_paid=True)
    first = await worker.run(input_value=realization(), arm_id="clean")
    second = await worker.run(input_value=realization(), arm_id="clean")
    assert isinstance(first, WorkerFailure) and isinstance(second, WorkerFailure)
    assert second.error_type == "BudgetHalted"
    assert len(wire.requests) == 1
    routing = json.loads(wire.requests[0].content)["provider"]
    assert routing["only"] == ["novita/fp8"] and routing["allow_fallbacks"] is False
    assert routing["data_collection"] == "deny" and routing["zdr"] is True


@pytest.mark.parametrize("rejection", ["parameters", "body"])
@pytest.mark.asyncio
async def test_local_rejection_keeps_ledger_open_and_reservation_consumed(
    wire: Wire, rejection: str
) -> None:
    from assay.adapters.consistency import _Admission, _BoundedClient

    policy = qwen_smoke_settings().model_copy(update={"max_total_requests": 2})
    admission = _Admission(policy)
    client = factory().create()
    bounded = _BoundedClient(client, admission, QWEN_NOVITA.model)
    bad = dataclasses.replace(
        params(),
        **({"reasoning": True} if rejection == "parameters" else {"system": "x" * 65_536}),
    )
    try:
        result = await bounded.complete_result(bad)
        assert isinstance(result, CompletionNotSent)
        assert not admission.halted and not bounded.uncertain and not wire.requests
        assert admission.requests == 1
        assert bounded.accounting().amount == 0
        assert bounded.accounting().coverage == "measured"
        assert bounded.accounting().usage == {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0}
    finally:
        await client.aclose()
    later = factory().create()
    next_attempt = _BoundedClient(later, admission, QWEN_NOVITA.model)
    try:
        assert isinstance(await next_attempt.complete_result(params()), LLMResponse)
        refused = await next_attempt.complete_result(params())
        assert isinstance(refused, WorkerFailure) and refused.error_type == "RequestLimit"
        assert admission.requests == 2 and len(wire.requests) == 1
    finally:
        await later.aclose()


@pytest.mark.asyncio
async def test_body_limit_boundary_excludes_headers(wire: Wire) -> None:
    client = factory().create()
    try:
        await client.complete(params())
    finally:
        await client.aclose()
    body_size = len(wire.requests[0].content)
    for limit in (body_size, body_size - 1):
        client = OpenRouterFactory(
            QWEN_NOVITA.model_copy(update={"max_request_body_bytes": limit}), "test-key"
        ).create()
        try:
            result = await client.complete_result(params())
            assert isinstance(result, LLMResponse if limit == body_size else CompletionNotSent)
        finally:
            await client.aclose()
    assert len(wire.requests) == 2


@pytest.mark.asyncio
async def test_worker_preserves_known_zero_for_local_rejection(wire: Wire) -> None:
    owner = OpenRouterFactory(
        QWEN_NOVITA.model_copy(update={"max_request_body_bytes": 1}), "test-key"
    )
    worker = ConsistencyWorker(owner, qwen_smoke_settings(), allow_paid=True)
    for _ in range(2):
        result = await worker.run(input_value=realization(), arm_id="clean")
        assert isinstance(result, WorkerFailure) and result.error_type == "InvalidRequest"
        assert result.accounting.amount == 0 and result.accounting.coverage == "measured"
        assert not result.trace["billing_uncertain"]
    assert not wire.requests


@pytest.mark.asyncio
async def test_success_then_no_send_preserves_paid_usage(wire: Wire) -> None:
    from assay.adapters.consistency import _Admission, _BoundedClient

    client = factory().create()
    admission = _Admission(qwen_smoke_settings())
    bounded = _BoundedClient(client, admission, QWEN_NOVITA.model)
    try:
        assert isinstance(await bounded.complete_result(params()), LLMResponse)
        refused = await bounded.complete_result(dataclasses.replace(params(), reasoning=True))
        assert isinstance(refused, CompletionNotSent)
        assert not admission.halted and not bounded.uncertain
        accounting = bounded.accounting()
        assert accounting.amount == 0.0000205 and accounting.coverage == "estimated"
        assert accounting.usage == {"llm_calls": 1, "input_tokens": 100, "output_tokens": 50}
        assert admission.requests == 2 and len(wire.requests) == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_failure_name_alone_does_not_assert_no_send(wire: Wire) -> None:
    from assay.adapters.consistency import _Admission, _BoundedClient

    client = factory().create()
    admission = _Admission(qwen_smoke_settings())
    bounded = _BoundedClient(client, admission, QWEN_NOVITA.model)
    try:
        with patch.object(
            client, "complete_result", return_value=WorkerFailure("InvalidRequest", "unknown")
        ):
            result = await bounded.complete_result(params())
        assert isinstance(result, WorkerFailure)
        assert admission.halted and bounded.uncertain
        assert bounded.accounting().amount is None
    finally:
        await client.aclose()
