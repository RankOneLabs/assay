from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import paa_contracts
import pytest

from assay.canonical import canonical_json, digest_bytes
from assay.execution import (
    Accounting,
    EvaluationSuccess,
    RunSucceeded,
    WorkerFailure,
    WorkerSuccess,
    _dispatch_worker,
    _worker_supports_coordinates,
    execute_plan,
)
from assay.models import (
    Arm,
    CellCoordinate,
    EvaluatorDeclaration,
    Realization,
    RuntimeProfile,
    StudySnapshot,
    Subject,
)
from assay.planning import compile_plan
from assay.store import ObjectStore
from assay.verify import verify_manifest


class FakeWorker:
    def configuration(self, arm_id: str) -> dict[str, Any]:
        return {"id": "fake", "version": "1"}

    async def run(self, *, input_value: Any, arm_id: str) -> WorkerSuccess | WorkerFailure:
        usage = Accounting(usage={"input_tokens": 3})
        if input_value["subject"] == "fails":
            return WorkerFailure("FixtureFailure", "intentional", accounting=usage)
        return WorkerSuccess({"score": 1 if arm_id == "candidate" else 0}, accounting=usage)


class FakeEvaluator:
    def configuration(self) -> dict[str, Any]:
        return {"version": "quality-v1"}

    async def evaluate(
        self, *, input_value: Any, output: Any, coordinate: Any
    ) -> EvaluationSuccess:
        return EvaluationSuccess(float(output["score"]), detail={"coordinate": coordinate.id})


def default_runtime(
    store: ObjectStore, *, id: str = "pier", version: str = "1.0.0"
) -> RuntimeProfile:
    configuration_ref = str(store.publish_json({"backend": id, "version": version}))
    return RuntimeProfile(id=id, version=version, configuration_ref=configuration_ref)


@dataclass
class ExecutionFixture:
    store: ObjectStore
    snapshot: StudySnapshot
    plan_bytes: bytes

    @property
    def arguments(self) -> dict[str, Any]:
        return {
            "plan_bytes": self.plan_bytes,
            "authorization": digest_bytes(self.plan_bytes),
            "snapshot": self.snapshot,
            "store": self.store,
            "workers": {arm.id: FakeWorker() for arm in self.snapshot.arms},
            "evaluators": {"quality": FakeEvaluator()},
        }


def execution_fixture(
    store: ObjectStore,
    *,
    subject_ids: tuple[str, ...] = ("ok", "fails"),
    worker_repeats: int = 2,
    evaluator_repeats: int = 2,
    concurrency: int = 4,
) -> ExecutionFixture:
    def publish(value: Any) -> str:
        return str(store.publish_json(value))

    subjects = tuple(
        Subject(
            id=value,
            label=value,
            digest=publish({"subject": value}),
            partition="test",
            payload_ref=publish({"subject": value}),
        )
        for value in subject_ids
    )
    arms = tuple(
        Arm(id=value, worker=FakeWorker().configuration(value), intervention={"kind": value})
        for value in ("reference", "candidate")
    )
    realizations = tuple(
        Realization(
            subject_id=subject.id,
            arm_id=arm.id,
            digest=publish({"subject": subject.id, "arm": arm.id}),
            artifact_ref=publish({"subject": subject.id, "arm": arm.id}),
        )
        for subject in subjects
        for arm in arms
    )
    identity = {
        "property": "quality",
        "target": "output",
        "technique": "deterministic",
        "evaluation_basis": {"kind": "rubric", "ref": "quality-v1"},
        "epistemic_status": "proxy",
        "version": "1",
        "authority": "advisory",
    }
    companion = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": "https://assay.test/scalar.schema.json",
        "allOf": [
            {"$ref": "https://paa.dev/paa-evidence-record.schema.json"},
            {
                "properties": {
                    "verdict": {
                        "properties": {
                            "value": {"type": "number", "minimum": 0, "maximum": 1},
                        }
                    }
                }
            },
        ],
    }
    evaluator = EvaluatorDeclaration(
        id="quality",
        identity=identity,
        payload_schema=companion["$id"],
        payload_schema_ref=publish(companion),
        configuration=FakeEvaluator().configuration(),
        basis_ref=publish({"rubric": "quality-v1"}),
        repeats=evaluator_repeats,
    )
    task = {
        "task": "fixture_quality",
        "version": 7,
        "description": "Test experiment",
        "boundary": {"input": "prompt", "output": "response"},
        "initial_position": "hitl",
        "deployment": "shadow",
        "evaluators": [identity],
        "position_policy": {"hitl": "offline", "hotl": "offline"},
        "promotion": {
            "from": "hitl",
            "to": "hotl",
            "report": "quality",
            "window": {"kind": "cases", "size": 10},
            "execution": "operator_approval",
        },
        "demotion": {
            "from": "hotl",
            "to": "hitl",
            "trigger": "operator",
            "window": {"kind": "cases", "size": 1},
        },
    }
    snapshot = StudySnapshot(
        subjects=subjects,
        arms=arms,
        realizations=realizations,
        evaluators=(evaluator,),
        paa_task_ref=publish(task),
        pricing_catalog_ref=publish({"rates": None}),
        task_schema_ref=publish(paa_contracts.load_schema("paa-task")),
        evidence_schema_ref=publish(paa_contracts.load_schema("paa-evidence-record")),
        operating_schema_ref=publish(paa_contracts.load_schema("paa-operating-record")),
    )
    plan = compile_plan(
        snapshot,
        snapshot_ref=publish(snapshot.model_dump(mode="json")),
        worker_repeats=worker_repeats,
        jig_revision="55081e8",
        concurrency=concurrency,
    )
    return ExecutionFixture(store, snapshot, canonical_json(plan.model_dump(mode="json")))


async def test_end_to_end_preserves_failures_and_completes_coordinates(tmp_path: Any) -> None:
    fixture = execution_fixture(ObjectStore(tmp_path))
    result = await execute_plan(**fixture.arguments)
    assert isinstance(result, RunSucceeded), result
    assert result.manifest.status == "complete"
    assert len(result.manifest.execution_records) == 8
    assert len(result.manifest.evaluation_records) == 16
    assert len(result.manifest.operating_records) == 16  # 8 workers + 8 actual evaluator attempts
    records = [
        json.loads(fixture.store.read_bytes(ref))
        for ref in result.manifest.execution_records.values()
    ]
    assert sum(record["status"] == "failed" for record in records) == 4
    assert all(record["started_at"].startswith("20") for record in records)
    evaluations = [
        json.loads(fixture.store.read_bytes(ref))
        for ref in result.manifest.evaluation_records.values()
    ]
    evidence = [record for record in evaluations if "record_schema" in record]
    assert len(evidence) == 8
    assert all(record["task"] == "fixture_quality" for record in evidence)
    assert all(record["declaration_version"] == 7 for record in evidence)
    assert all(record["record_id"].startswith(result.manifest.run_id) for record in evidence)
    assert verify_manifest(fixture.store, str(result.manifest_ref)) == ()


async def test_snapshot_drift_makes_zero_worker_calls(tmp_path: Any) -> None:
    fixture = execution_fixture(ObjectStore(tmp_path))
    arguments = fixture.arguments
    arguments["snapshot"] = fixture.snapshot.model_copy(
        update={"pricing_catalog_ref": "sha256:" + "c" * 64}
    )
    result = await execute_plan(**arguments)
    assert not isinstance(result, RunSucceeded)
    assert "snapshot" in result.message


def _sample_coordinate() -> CellCoordinate:
    return CellCoordinate(
        subject_id="ok", arm_id="candidate", worker_repeat=0, realization_ref="sha256:" + "a" * 64
    )


async def test_dispatch_uses_legacy_run_for_a_structurally_legacy_worker() -> None:
    calls: list[tuple[Any, Any]] = []

    class LegacyWorker:
        def configuration(self, arm_id: str) -> dict[str, Any]:
            return {"id": "legacy", "version": "1"}

        async def run(self, *, input_value: Any, arm_id: str) -> WorkerSuccess:
            calls.append((input_value, arm_id))
            return WorkerSuccess({"ok": True})

    worker = LegacyWorker()
    assert _worker_supports_coordinates(worker) is False
    result = await _dispatch_worker(
        worker, arm_id="candidate", cell=_sample_coordinate(), input_value={"prompt": "x"}
    )
    assert isinstance(result, WorkerSuccess)
    assert calls == [({"prompt": "x"}, "candidate")]


async def test_dispatch_never_uses_run_cell_unless_the_flag_is_explicitly_true() -> None:
    # A worker that defines run_cell but does not (or falsely) advertise the
    # capability must still go through the legacy structural path.
    calls: list[str] = []

    class UnadvertisedWorker:
        supports_cell_coordinates = False

        def configuration(self, arm_id: str) -> dict[str, Any]:
            return {"id": "unadvertised", "version": "1"}

        async def run(self, *, input_value: Any, arm_id: str) -> WorkerSuccess:
            calls.append("run")
            return WorkerSuccess({"ok": True})

        async def run_cell(self, *, input_value: Any, coordinate: CellCoordinate) -> WorkerSuccess:
            calls.append("run_cell")
            return WorkerSuccess({"ok": True})

    worker = UnadvertisedWorker()
    assert _worker_supports_coordinates(worker) is False
    await _dispatch_worker(
        worker, arm_id="candidate", cell=_sample_coordinate(), input_value={"prompt": "x"}
    )
    assert calls == ["run"]


async def test_dispatch_delivers_the_exact_immutable_coordinate_when_advertised() -> None:
    received: list[CellCoordinate] = []

    class CoordinateWorker:
        supports_cell_coordinates = True

        def configuration(self, arm_id: str) -> dict[str, Any]:
            return {"id": "coordinate-aware", "version": "1"}

        async def run_cell(self, *, input_value: Any, coordinate: CellCoordinate) -> WorkerSuccess:
            received.append(coordinate)
            return WorkerSuccess({"ok": True})

        async def run(self, *, input_value: Any, arm_id: str) -> WorkerFailure:
            raise AssertionError("legacy path must not be used when the flag is advertised")

    worker = CoordinateWorker()
    assert _worker_supports_coordinates(worker) is True
    coordinate = _sample_coordinate()
    result = await _dispatch_worker(
        worker, arm_id="candidate", cell=coordinate, input_value={"prompt": "x"}
    )
    assert isinstance(result, WorkerSuccess)
    assert received == [coordinate]
    assert received[0] is coordinate


async def test_adapter_internal_type_error_propagates_and_is_not_a_fallback_signal() -> None:
    calls: list[str] = []

    class BuggyCoordinateWorker:
        supports_cell_coordinates = True

        def configuration(self, arm_id: str) -> dict[str, Any]:
            return {"id": "buggy", "version": "1"}

        async def run_cell(self, *, input_value: Any, coordinate: CellCoordinate) -> WorkerSuccess:
            calls.append("run_cell")
            raise TypeError("adapter bug: wrong argument shape internally")

        async def run(self, *, input_value: Any, arm_id: str) -> WorkerSuccess:
            calls.append("run")
            return WorkerSuccess({"ok": True})

    worker = BuggyCoordinateWorker()
    with pytest.raises(TypeError, match="adapter bug"):
        await _dispatch_worker(
            worker, arm_id="candidate", cell=_sample_coordinate(), input_value={"prompt": "x"}
        )
    assert calls == ["run_cell"]


async def test_coordinate_aware_worker_end_to_end_preserves_ordering_and_receives_coordinates(
    tmp_path: Any,
) -> None:
    received: dict[str, CellCoordinate] = {}

    class CoordinateFakeWorker:
        supports_cell_coordinates = True

        def configuration(self, arm_id: str) -> dict[str, Any]:
            return {"id": "fake", "version": "1"}

        async def run_cell(
            self, *, input_value: Any, coordinate: CellCoordinate
        ) -> WorkerSuccess | WorkerFailure:
            received[coordinate.id] = coordinate
            if input_value["subject"] == "fails":
                return WorkerFailure("FixtureFailure", "intentional")
            return WorkerSuccess({"score": 1 if coordinate.arm_id == "candidate" else 0})

    fixture = execution_fixture(ObjectStore(tmp_path))
    arguments = fixture.arguments
    arguments["workers"] = {arm.id: CoordinateFakeWorker() for arm in fixture.snapshot.arms}
    result = await execute_plan(**arguments)
    assert isinstance(result, RunSucceeded), result
    assert result.manifest.status == "complete"
    assert len(result.manifest.execution_records) == 8
    plan_cell_ids = {
        f"{cell['subject_id']}:{cell['arm_id']}:w{cell['worker_repeat']}"
        for cell in json.loads(fixture.plan_bytes)["cells"]
    }
    assert set(received) == plan_cell_ids
    for cell_id, coordinate in received.items():
        assert coordinate.id == cell_id
    assert verify_manifest(fixture.store, str(result.manifest_ref)) == ()
