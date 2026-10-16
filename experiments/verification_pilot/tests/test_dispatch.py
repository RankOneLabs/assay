"""Pilot dispatch keys isolate runs, cells, and turns."""

import asyncio
from typing import Any

from assay.execution import WorkerFailure
from assay.models import CellCoordinate
from verification_pilot.bridge import PilotWorker
from verification_pilot.dispatch import cell_idempotency_key, turn_idempotency_key
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
