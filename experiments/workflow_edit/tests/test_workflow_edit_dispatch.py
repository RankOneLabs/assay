"""Workflow dispatch binds one stable key and the authorized route per arm."""

from pathlib import Path
from typing import Any

from assay.adapters.smithers import SmithersClient, SmithersFactory
from assay.execution import WorkerSuccess
from assay.models import CellCoordinate
from workflow_edit.dispatch import SmithersBoundWorker, cell_idempotency_key


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
