"""Workflow dispatch binds one stable key and the authorized route per arm."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from assay.adapters.smithers import SmithersClient, SmithersFactory
from assay.execution import WorkerSuccess
from assay.models import CellCoordinate
from assay.store import ObjectStore
from workflow_edit.dispatch import (
    SmithersBoundWorker,
    SmithersBridgeCellDelegate,
    cell_idempotency_key,
)


class Delegate:
    supports_cell_coordinates = True

    def __init__(self) -> None:
        self.seen_key: str | None = None

    def configuration(self, arm_id: str) -> dict[str, Any]:
        return {"arm_id": arm_id, "runtime_id": "pier"}

    async def run_cell(
        self, *, input_value: Any, coordinate: CellCoordinate, client: SmithersClient
    ) -> WorkerSuccess:
        self.seen_key = client._idempotency_key
        return WorkerSuccess(output=input_value)


async def test_cell_key_and_worker_configuration(tmp_path: Path) -> None:
    routing = tmp_path / "routing_config.yaml"
    routing.write_text(
        "machines:\n  mcbain:\n    backend: vllm\n"
        "models:\n  qwen:\n    machines: [mcbain]\n"
        "    backend_tags:\n      vllm: qwen:Q8\n"
    )
    factory = SmithersFactory("qwen", "mcbain", routing, "http://smithers.test")
    delegate = Delegate()
    worker = SmithersBoundWorker(delegate, factory, "run-1")
    coordinate = CellCoordinate(
        subject_id="subject", arm_id="mess-low", worker_repeat=0,
        realization_ref="sha256:" + "a" * 64,
    )
    key = cell_idempotency_key("run-1", coordinate)
    assert key == cell_idempotency_key("run-1", coordinate)
    assert key != cell_idempotency_key("run-2", coordinate)
    configuration = worker.configuration("mess-low")
    assert configuration["smithers"]["machine"] == "mcbain"
    assert configuration["smithers"]["model"] == "qwen"
    assert configuration["smithers"]["resolved_backend_tag"] == "qwen:Q8"
    assert "idempotency_key" not in configuration["smithers"]
    client = worker.client_for_cell("run-1", coordinate)
    try:
        assert client._idempotency_key == key
    finally:
        await client.aclose()
    assert await worker.run_cell(input_value={"candidate": "done"}, coordinate=coordinate) == (
        WorkerSuccess(output={"candidate": "done"})
    )
    assert delegate.seen_key == key


class _Dispatch:
    """One bridge dispatch and what the runtime saw of it."""

    def __init__(self) -> None:
        self.result: Any = None
        self.accepted_at: datetime | None = None


async def _dispatch_one_cell(
    tmp_path: Path,
    monkeypatch: Any,
    *,
    dispatch_host_offset: timedelta = timedelta(0),
    poll_interval: float = 0.5,
    inference_seconds: float = 1.0,
    usage: Any = None,
) -> _Dispatch:
    """Run one cell through ``SmithersBridgeCellDelegate`` against a faked Smithers.

    ``dispatch_host_offset`` shifts the wall clock Smithers stamps its job
    with, exactly as a non-UTC dispatch host would.
    """
    routing = tmp_path / "routing_config.yaml"
    routing.write_text(
        "machines:\n  mcbain:\n    backend: vllm\n"
        "models:\n  qwen:\n    machines: [mcbain]\n"
        "    backend_tags:\n      vllm: qwen:Q8\n"
    )
    factory = SmithersFactory(
        "qwen", "mcbain", routing, "http://smithers.test", poll_interval=poll_interval
    )
    coordinate = CellCoordinate(
        subject_id="subject", arm_id="mess-low", worker_repeat=0,
        realization_ref="sha256:" + "a" * 64,
    )
    # What the dispatch host's own clock reads, naive and unlabelled on the wire.
    started = datetime.now(UTC).replace(tzinfo=None) + dispatch_host_offset - timedelta(seconds=4)
    created = started - timedelta(seconds=2)
    completed = started + timedelta(seconds=inference_seconds)

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"job_id": "job-1"})
        return httpx.Response(200, json={
            "job_id": "job-1", "status": "complete", "machine": "mcbain", "model": "qwen",
            "created_at": created.isoformat(), "started_at": started.isoformat(),
            "completed_at": completed.isoformat(), "result": {"content": "candidate text"},
        })

    client = factory.create(idempotency_key=cell_idempotency_key("run-1", coordinate))
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(SmithersFactory, "create", lambda self, *, idempotency_key: client)

    observed = _Dispatch()

    class Runtime:
        def run_cell(self, request: Any, *, accepted_at: datetime) -> Any:
            observed.accepted_at = accepted_at
            assert request.content == "candidate text"
            return SimpleNamespace(
                cell_id=coordinate.id, outcome=SimpleNamespace(kind="candidate"),
                usage=usage,
                artifacts={
                    "manifest.json": b"{}", "candidate-index.json": b"[]",
                    "candidate.patch": b"patch", "tree-digest.txt": b"digest",
                    "result.json": b"{}", "configuration.json": b"{}",
                    "trajectory.json": b"{}",
                },
            )

    runtime = Runtime()
    delegate = SmithersBridgeCellDelegate(
        store=ObjectStore(tmp_path / "store"),
        runtime_factory=lambda: runtime,
        request_builder=lambda value, cell, content: SimpleNamespace(
            cell_id=cell.id, content=content
        ),
        bridge_configuration={"runtime": "pier-test"},
    )
    worker = SmithersBoundWorker(delegate, factory, "run-1")
    observed.result = await worker.run_cell(
        input_value={"prompt": "edit this"}, coordinate=coordinate
    )
    return observed


@pytest.mark.parametrize("dispatch_host_offset", [timedelta(0), timedelta(hours=-7)])
async def test_production_delegate_passes_smithers_acceptance_to_bridge(
    tmp_path: Path, monkeypatch: Any, dispatch_host_offset: timedelta
) -> None:
    """The anchor is a local duration, so the dispatch host's timezone cannot shift it.

    Smithers stamps jobs with ``datetime.now()`` on its own host, so a
    dispatch host that is not on UTC reports a wall clock hours away from
    this one. Reading that as an instant would charge the offset to the
    cell; only ``completed_at - started_at`` is clock-independent.
    """
    observed = await _dispatch_one_cell(
        tmp_path, monkeypatch, dispatch_host_offset=dispatch_host_offset
    )
    assert isinstance(observed.result, WorkerSuccess)
    assert observed.result.output["candidate_ref"] is not None
    assert observed.result.trace["smithers"]["queue_latency_seconds"] == 2.0
    # One second of inference was charged, whatever the dispatch host's clock read.
    assert observed.accepted_at is not None
    charged = (datetime.now(UTC) - observed.accepted_at).total_seconds()
    assert 1.5 <= charged < 10.0


async def test_the_poll_that_observed_completion_is_charged_to_the_cell(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Completion is learned at a poll, so the whole poll interval is spent, not granted.

    Anchoring at the observing poll would place acceptance later than it
    really was and hand the cell up to one extra interval of budget.
    """
    observed = await _dispatch_one_cell(
        tmp_path, monkeypatch, poll_interval=30.0, inference_seconds=1.0
    )
    assert observed.accepted_at is not None
    charged = (datetime.now(UTC) - observed.accepted_at).total_seconds()
    assert 31.0 <= charged < 40.0


async def test_a_dispatched_cell_records_the_bridge_trial_cost(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Only the guarded route is priced, so a successful cell's coverage is mixed.

    Smithers reports no billing at all, so reporting the bridge amount as
    ``measured`` would claim the dispatch leg cost nothing.
    """
    observed = await _dispatch_one_cell(
        tmp_path,
        monkeypatch,
        usage=SimpleNamespace(
            prompt_tokens=120, completion_tokens=34, cost_usd=0.0021, requests=1
        ),
    )
    assert isinstance(observed.result, WorkerSuccess)
    assert observed.result.accounting.amount == 0.0021
    assert observed.result.accounting.coverage == "mixed"
    assert observed.result.accounting.usage == {
        "prompt_tokens": 120.0, "completion_tokens": 34.0, "requests": 1.0
    }


async def test_a_bridge_result_without_usage_is_uncertain_not_free(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A dispatched attempt that reported no usage has an unknown cost, never zero."""
    observed = await _dispatch_one_cell(tmp_path, monkeypatch, usage=None)
    assert isinstance(observed.result, WorkerSuccess)
    assert observed.result.accounting.coverage == "uncertain"
    assert observed.result.accounting.amount is None
