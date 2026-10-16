"""Pinned Smithers identity, retry, and worker-acceptance timing."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from jig.core.types import CompletionParams, Message, Role

from assay.adapters.smithers import SmithersFactory
from assay.canonical import canonical_json
from assay.execution import WorkerFailure


def _routing(path: Path, tag: str = "qwen:Q8") -> None:
    path.write_text(
        "machines:\n  mcbain:\n    backend: vllm\n"
        "models:\n  qwen:\n    machines: [mcbain]\n"
        f"    backend_tags:\n      vllm: {tag}\n"
    )


def _factory(tmp_path: Path) -> SmithersFactory:
    routing = tmp_path / "routing_config.yaml"
    _routing(routing)
    return SmithersFactory(
        model="qwen", machine="mcbain", routing_config=routing,
        dispatch_url="http://smithers.test", poll_interval=0,
    )


def _job(*, model: str = "qwen", machine: str = "mcbain", seconds: int = 30) -> dict[str, Any]:
    created = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)
    started = created + timedelta(seconds=120)
    return {
        "job_id": "job-1", "status": "complete", "model": model, "machine": machine,
        "created_at": created.isoformat(), "started_at": started.isoformat(),
        "completed_at": (started + timedelta(seconds=seconds)).isoformat(),
        "result": {"content": "done"},
    }


def _params() -> CompletionParams:
    return CompletionParams(messages=[Message(role=Role.USER, content="hello")])


def _task(*, model: str = "qwen:Q8", usage: bool = True) -> dict[str, Any]:
    task: dict[str, Any] = {"job_id": "job-1", "status": "complete"}
    if usage:
        task["usage"] = {"model": model, "input_tokens": 11, "output_tokens": 7}
    return task


def _transport(job: dict[str, Any], task: dict[str, Any] | None = None) -> httpx.MockTransport:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.host == "mcbain":
            return httpx.Response(200, json=task if task is not None else _task())
        return httpx.Response(200, json={"job_id": "job-1"} if request.method == "POST" else job)

    return httpx.MockTransport(respond)


@pytest.mark.parametrize(
    ("job", "cause"),
    [
        (_job(machine="frink"), "MachineIdentityMismatch"),
        (_job(model="other"), "ModelIdentityMismatch"),
    ],
)
async def test_rejects_wrong_job_identity(
    tmp_path: Path, job: dict[str, Any], cause: str
) -> None:
    factory = _factory(tmp_path)
    client = factory.create(idempotency_key="cell-1")
    client._http = httpx.AsyncClient(transport=_transport(job))
    try:
        result = await client.complete_result(_params())
    finally:
        await client.aclose()
    assert isinstance(result, WorkerFailure)
    assert result.error_type == cause


async def test_routing_tag_is_authorized_and_rechecked(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    authorized = canonical_json(factory.configuration())
    client = factory.create(idempotency_key="cell-1")
    assert canonical_json(client.configuration()) == authorized
    assert "idempotency_key" not in client.configuration()
    _routing(factory.routing_config, "qwen:Q4")
    client._http = httpx.AsyncClient(transport=_transport(_job()))
    try:
        result = await client.complete_result(_params())
    finally:
        await client.aclose()
    assert isinstance(result, WorkerFailure)
    assert result.error_type == "ResolvedTagIdentityMismatch"


async def test_reported_resolved_tag_must_match(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    client = factory.create(idempotency_key="cell-1")
    job = {**_job(), "resolved_backend_tag": "qwen:Q4"}
    client._http = httpx.AsyncClient(transport=_transport(job))
    try:
        result = await client.complete_result(_params())
    finally:
        await client.aclose()
    assert isinstance(result, WorkerFailure)
    assert result.error_type == "ResolvedTagIdentityMismatch"


async def test_dropped_response_retries_same_submission_and_reports_clock(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    seen: list[dict[str, Any]] = []
    completions = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal completions
        if request.url.host == "mcbain":
            return httpx.Response(200, json=_task())
        if request.method == "POST":
            seen.append(json.loads(request.content))
            if len(seen) == 1:
                raise httpx.ReadError("response dropped")
            return httpx.Response(200, json={"job_id": "job-1"})
        completions += 1
        return httpx.Response(200, json=_job())

    client = factory.create(idempotency_key="cell-1")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        result = await client.complete_result(_params())
    finally:
        await client.aclose()
    assert not isinstance(result, WorkerFailure)
    assert len(seen) == 2 and seen[0] == seen[1]
    assert seen[0]["idempotency_key"] == "cell-1"
    assert completions == 1
    assert result.usage.input_tokens == 11 and result.usage.output_tokens == 7
    assert result.model == "qwen:Q8"
    assert client.diagnostics() == {
        "job_id": "job-1",
        "worker_model": "qwen:Q8",
        "started_at": _job()["started_at"],
        "queue_latency_seconds": 120.0,
        "time_from_acceptance_seconds": 30.0,
    }


async def test_changed_keyed_request_surfaces_409(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    first_body: dict[str, Any] | None = None

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal first_body
        if request.url.host == "mcbain":
            return httpx.Response(200, json=_task())
        if request.method == "GET":
            return httpx.Response(200, json=_job())
        body = json.loads(request.content)
        if first_body is None:
            first_body = body
            return httpx.Response(200, json={"job_id": "job-1"})
        if body != first_body:
            return httpx.Response(409, json={"detail": "conflict"})
        return httpx.Response(200, json={"job_id": "job-1"})

    transport = httpx.MockTransport(respond)
    first = factory.create(idempotency_key="cell-1")
    first._http = httpx.AsyncClient(transport=transport)
    client = factory.create(idempotency_key="cell-1")
    client._http = httpx.AsyncClient(transport=transport)
    try:
        original = await first.complete_result(_params())
        changed = CompletionParams(messages=[Message(role=Role.USER, content="changed")])
        result = await client.complete_result(changed)
    finally:
        await first.aclose()
        await client.aclose()
    assert not isinstance(original, WorkerFailure)
    assert isinstance(result, WorkerFailure)
    assert result.error_type == "IdempotencyConflictError"


async def test_acceptance_budget_excludes_queue_time(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    client = factory.create(idempotency_key="cell-1")
    client._http = httpx.AsyncClient(transport=_transport(_job(seconds=901)))
    try:
        result = await client.complete_result(_params())
    finally:
        await client.aclose()
    assert isinstance(result, WorkerFailure)
    assert result.error_type == "AcceptanceDeadlineExceeded"
    assert client.diagnostics()["queue_latency_seconds"] == 120.0


async def test_running_job_uses_recorded_completion_clock(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    client = factory.create(idempotency_key="cell-1")
    polls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal polls
        if request.url.host == "mcbain":
            return httpx.Response(200, json=_task())
        if request.method == "POST":
            return httpx.Response(200, json={"job_id": "job-1"})
        polls += 1
        if polls == 1:
            return httpx.Response(
                200, json={**_job(), "status": "running", "completed_at": None, "result": None}
            )
        return httpx.Response(200, json=_job())

    client._http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        result = await client.complete_result(_params())
    finally:
        await client.aclose()
    assert not isinstance(result, WorkerFailure)
    assert polls == 2


@pytest.mark.parametrize(
    ("task", "cause"),
    [
        (_task(usage=False), "UsageUnavailable"),
        (_task(model="qwen:Q4"), "ResolvedTagIdentityMismatch"),
        ({**_task(), "job_id": "job-2"}, "IdentityMismatch"),
    ],
)
async def test_worker_task_attests_usage_and_model(
    tmp_path: Path, task: dict[str, Any], cause: str
) -> None:
    client = _factory(tmp_path).create(idempotency_key="cell-1")
    client._http = httpx.AsyncClient(transport=_transport(_job(), task))
    try:
        result = await client.complete_result(_params())
    finally:
        await client.aclose()
    assert isinstance(result, WorkerFailure)
    assert result.error_type == cause


async def test_raw_payload_is_submitted_verbatim(tmp_path: Path) -> None:
    seen: list[dict[str, Any]] = []
    job = {**_job(), "result": {"content": "", "tool_calls": [{"id": "c1"}]}}

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.host == "mcbain":
            return httpx.Response(200, json=_task())
        if request.method == "POST":
            seen.append(json.loads(request.content))
            return httpx.Response(200, json={"job_id": "job-1"})
        return httpx.Response(200, json=job)

    client = _factory(tmp_path).create(idempotency_key="cell-1:t3")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    payload = {"messages": [{"role": "user", "content": "x"}], "tool_choice": "required"}
    try:
        completion = await client.complete_payload(payload)
    finally:
        await client.aclose()
    assert not isinstance(completion, WorkerFailure)
    assert seen[0]["payload"] == payload
    assert seen[0]["idempotency_key"] == "cell-1:t3"
    assert completion.result["tool_calls"] == [{"id": "c1"}]
    assert (completion.input_tokens, completion.output_tokens) == (11, 7)
