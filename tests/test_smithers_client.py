"""Pinned Smithers identity, retry, and worker-acceptance timing."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from jig.core.types import CompletionParams, Message, Role

from assay.adapters.smithers import SmithersFactory
from assay.canonical import canonical_json
from assay.execution import WorkerFailure

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

from workflow_edit.dispatch import SmithersBoundWorker  # noqa: E402


async def test_execution_checks_smithers_bound_worker_configuration(tmp_path: Path) -> None:
    from test_execution import execution_fixture

    from assay.canonical import digest_bytes
    from assay.execution import RunFailed, RunSucceeded, WorkerSuccess, execute_plan
    from assay.planning import compile_plan
    from assay.store import ObjectStore

    class Delegate:
        def configuration(self, arm_id: str) -> dict[str, str]:
            return {"id": "smithers-fixture", "version": "1", "arm_id": arm_id}

        async def run_cell(
            self, *, input_value: Any, coordinate: Any, client: Any
        ) -> WorkerSuccess:
            return WorkerSuccess({"score": 1})

    store = ObjectStore(tmp_path / "store")
    fixture = execution_fixture(store, subject_ids=("ok",), worker_repeats=1)
    routing = tmp_path / "routing_config.yaml"
    _routing(routing)
    factory = SmithersFactory("qwen", "mcbain", routing, "http://smithers.test")
    worker = SmithersBoundWorker(Delegate(), factory, "run-1")
    snapshot = fixture.snapshot.model_copy(update={
        "arms": tuple(
            arm.model_copy(update={"worker": worker.configuration(arm.id)})
            for arm in fixture.snapshot.arms
        )
    })
    snapshot_ref = str(store.publish_json(snapshot.model_dump(mode="json")))
    plan = compile_plan(
        snapshot, snapshot_ref=snapshot_ref, worker_repeats=1,
        jig_revision="55081e8", concurrency=4,
    )
    plan_bytes = canonical_json(plan.model_dump(mode="json"))
    args = fixture.arguments | {
        "snapshot": snapshot,
        "plan_bytes": plan_bytes,
        "authorization": digest_bytes(plan_bytes),
        "workers": {arm.id: worker for arm in snapshot.arms},
    }
    accepted = await execute_plan(**args)
    assert isinstance(accepted, RunSucceeded), accepted

    _routing(routing, "qwen:Q4")
    rejected = await execute_plan(**args)
    assert isinstance(rejected, RunFailed)
    assert "worker configuration mismatch" in rejected.message


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
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(
            200, json={"job_id": "job-1"} if request.method == "POST" else job
        )
    ))
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
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(
            200, json={"job_id": "job-1"} if request.method == "POST" else _job()
        )
    ))
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
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(
            200, json={"job_id": "job-1"} if request.method == "POST" else job
        )
    ))
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
    assert client.diagnostics() == {
        "started_at": _job()["started_at"],
        "queue_latency_seconds": 120.0,
        "time_from_acceptance_seconds": 30.0,
    }


async def test_changed_keyed_request_surfaces_409(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    first_body: dict[str, Any] | None = None

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal first_body
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
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(
            200, json={"job_id": "job-1"} if request.method == "POST" else _job(seconds=901)
        )
    ))
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
