"""Pilot dispatch keys isolate runs, cells, and turns."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from assay.execution import WorkerFailure
from assay.models import CellCoordinate
from assay.store import ObjectStore
from verification_pilot.bridge import PilotWorker
from verification_pilot.dispatch import cell_idempotency_key, turn_idempotency_key
from verification_pilot.run import run_live
from verification_pilot.study import pilot_subjects


def test_dispatch_keys() -> None:
    cell = CellCoordinate(subject_id="subject", arm_id="t1-native", worker_repeat=0,
                          realization_ref="sha256:" + "0" * 64)
    key = cell_idempotency_key("run-1", cell)
    assert key == cell_idempotency_key("run-1", cell)
    assert key != cell_idempotency_key("run-2", cell)
    assert turn_idempotency_key(key, 1) != turn_idempotency_key(key, 2)


def test_worker_refuses_a_realization_that_differs_from_the_subject() -> None:
    subject = pilot_subjects()[0]

    class NoDispatch:
        async def run_cell(self, *, input_value: Any, coordinate: CellCoordinate) -> Any:
            raise AssertionError("tampered input reached dispatch")

    class SubjectMap:
        subjects = {subject.id: subject}

    worker = PilotWorker(adapter=NoDispatch(), bridge=SubjectMap())  # type: ignore[arg-type]
    cell = CellCoordinate(subject_id=subject.id, arm_id="t1-native", worker_repeat=0,
                          realization_ref="sha256:" + "0" * 64)
    result = asyncio.run(worker.run_cell(input_value={"task": "different"}, coordinate=cell))
    assert isinstance(result, WorkerFailure)
    assert result.error_type == "RealizationMismatch"


def test_paid_smoke_compiles_the_guarded_route_without_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_dispatch(**kwargs: Any) -> str:
        return "no-dispatch"

    monkeypatch.setattr("verification_pilot.run.execute_plan", no_dispatch)
    store = ObjectStore(tmp_path / "store")
    prepared, result = asyncio.run(run_live(
        store, image="sha256:" + "a" * 64, runs_root=tmp_path / "runs",
        routing_config=tmp_path / "unused.yaml", route="openrouter",
        smoke=True, api_key="test-key",
    ))
    assert result == "no-dispatch"
    plan = json.loads(prepared.plan_bytes)
    assert len(plan["cells"]) == 16
    configuration = json.loads(store.read_bytes(plan["runtime"]["configuration_ref"]))
    assert configuration["model_route"]["provider"] == "amazon-bedrock"
    assert configuration["turns"]["backend"] == "openrouter"
    assert "test-key" not in json.dumps(configuration)


def test_paid_route_requires_a_credential(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        asyncio.run(run_live(
            ObjectStore(tmp_path / "store"), image="sha256:" + "a" * 64,
            runs_root=tmp_path / "runs", routing_config=tmp_path / "unused.yaml",
            route="openrouter", smoke=True,
        ))
