"""Pilot dispatch keys isolate runs, cells, and turns."""

import asyncio
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from assay.execution import WorkerFailure
from assay.models import CellCoordinate
from assay.store import ObjectStore
from verification_pilot.bridge import PilotWorker, SpendGate
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
        spend_gate = None

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
        smoke=True, api_key="test-key", spend_gate=SpendGate(Decimal("2")),
    ))
    assert result == "no-dispatch"
    plan = json.loads(prepared.plan_bytes)
    assert len(plan["cells"]) == 8
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


def test_paid_route_requires_a_spend_cap(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="spend cap"):
        asyncio.run(run_live(
            ObjectStore(tmp_path / "store"), image="sha256:" + "a" * 64,
            runs_root=tmp_path / "runs", routing_config=tmp_path / "unused.yaml",
            route="openrouter", smoke=True, api_key="test-key",
        ))


def test_halted_spend_gate_admits_no_further_cell() -> None:
    from assay.execution import AdmissionHalt

    subject = pilot_subjects()[0]

    class NoDispatch:
        async def run_cell(self, *, input_value: Any, coordinate: CellCoordinate) -> Any:
            raise AssertionError("a halted run dispatched a cell")

    class SubjectMap:
        subjects = {subject.id: subject}
        spend_gate = SpendGate(Decimal("1"), halt="budget_exhausted")

    worker = PilotWorker(adapter=NoDispatch(), bridge=SubjectMap())  # type: ignore[arg-type]
    cell = CellCoordinate(subject_id=subject.id, arm_id="t1-native", worker_repeat=0,
                          realization_ref="sha256:" + "0" * 64)
    with pytest.raises(AdmissionHalt) as halted:
        asyncio.run(worker.run_cell(input_value=_input(subject), coordinate=cell))
    assert halted.value.code == "budget_exhausted"


def test_cell_stopped_by_the_cap_halts_the_run() -> None:
    from assay.execution import AdmissionHalt

    subject = pilot_subjects()[0]
    gate = SpendGate(Decimal("1"))

    class StoppedByCap:
        async def run_cell(self, *, input_value: Any, coordinate: CellCoordinate) -> Any:
            gate.halt = "budget_exhausted"
            return WorkerFailure("enforcement", "agent loop stopped: budget_exhausted",
                                 trace={"stopped": True})

    class SubjectMap:
        subjects = {subject.id: subject}
        spend_gate = gate

    worker = PilotWorker(adapter=StoppedByCap(), bridge=SubjectMap())  # type: ignore[arg-type]
    cell = CellCoordinate(subject_id=subject.id, arm_id="t1-native", worker_repeat=0,
                          realization_ref="sha256:" + "0" * 64)
    with pytest.raises(AdmissionHalt) as halted:
        asyncio.run(worker.run_cell(input_value=_input(subject), coordinate=cell))
    assert halted.value.code == "budget_exhausted"
    assert halted.value.trace == {"stopped": True}


def test_successful_cell_with_uncertain_billing_halts_the_run() -> None:
    from assay.execution import Accounting, AdmissionHalt, WorkerSuccess

    subject = pilot_subjects()[0]
    gate = SpendGate(Decimal("1"))
    accounting = Accounting(coverage="uncertain")

    class UncertainSuccess:
        async def run_cell(self, *, input_value: Any, coordinate: CellCoordinate) -> Any:
            gate.halt = "billing_uncertain"
            return WorkerSuccess({"cell_id": coordinate.id}, trace={"submitted": True},
                                 accounting=accounting)

    class SubjectMap:
        subjects = {subject.id: subject}
        spend_gate = gate

    worker = PilotWorker(adapter=UncertainSuccess(), bridge=SubjectMap())  # type: ignore[arg-type]
    cell = CellCoordinate(subject_id=subject.id, arm_id="t1-native", worker_repeat=0,
                          realization_ref="sha256:" + "0" * 64)
    with pytest.raises(AdmissionHalt) as halted:
        asyncio.run(worker.run_cell(input_value=_input(subject), coordinate=cell))
    assert halted.value.code == "billing_uncertain"
    assert halted.value.trace == {"submitted": True}
    assert halted.value.accounting == accounting


def _input(subject: Any) -> dict[str, Any]:
    from verification_pilot.arms import placement_for
    from verification_pilot.prompts import task_prompt
    from verification_pilot.session import contributor_blocks, rotated_blocks

    blocks = rotated_blocks(contributor_blocks(subject.migration), subject.rotation)
    return {"task": task_prompt(subject.migration), "repository": subject.repository,
            "migration": subject.migration.name, "location": subject.location,
            "rotation": subject.rotation, "blocks": [block.text for block in blocks],
            "placement": placement_for("t1-native")}
