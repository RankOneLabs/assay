"""Workflow dispatch binds one stable key and the authorized route per arm."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx

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


async def test_production_delegate_passes_smithers_acceptance_to_bridge(
    tmp_path: Path, monkeypatch: Any
) -> None:
    routing = tmp_path / "routing_config.yaml"
    routing.write_text(
        "machines:\n  mcbain:\n    backend: vllm\n"
        "models:\n  qwen:\n    machines: [mcbain]\n"
        "    backend_tags:\n      vllm: qwen:Q8\n"
    )
    factory = SmithersFactory("qwen", "mcbain", routing, "http://smithers.test")
    coordinate = CellCoordinate(
        subject_id="subject", arm_id="mess-low", worker_repeat=0,
        realization_ref="sha256:" + "a" * 64,
    )
    started = datetime.now(UTC) - timedelta(seconds=4)
    created = started - timedelta(seconds=2)
    completed = started + timedelta(seconds=1)

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

    class Runtime:
        accepted_at: datetime | None = None

        def run_cell(self, request: Any, *, accepted_at: datetime) -> Any:
            self.accepted_at = accepted_at
            assert request.content == "candidate text"
            return SimpleNamespace(
                cell_id=coordinate.id, outcome=SimpleNamespace(kind="candidate"),
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
    result = await worker.run_cell(input_value={"prompt": "edit this"}, coordinate=coordinate)
    assert isinstance(result, WorkerSuccess)
    assert result.output["candidate_ref"] is not None
    assert result.trace["smithers"]["queue_latency_seconds"] == 2.0
    assert runtime.accepted_at == started
