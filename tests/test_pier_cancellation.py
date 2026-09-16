from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import paa_contracts
import pytest

from assay.adapters.pier import BridgeTrialResult, PierAdapter, PierBridgeHandle
from assay.canonical import canonical_json, digest_bytes
from assay.execution import Accounting, EvaluationSuccess, WorkerFailure, execute_plan
from assay.models import (
    Arm,
    CellCoordinate,
    EvaluatorDeclaration,
    Realization,
    RuntimeProfile,
    StudySnapshot,
    Subject,
)
from assay.pier_protocol import PierExchange, RuntimeBinding
from assay.planning import compile_plan_v2
from assay.store import ObjectStore


def _binding() -> RuntimeBinding:
    return RuntimeBinding(
        runtime_version="lock-v1",
        image_digest="sha256:" + "1" * 64,
        configuration_ref="sha256:" + "2" * 64,
        package_digest="sha256:" + "3" * 64,
    )


def _coordinate() -> CellCoordinate:
    return CellCoordinate(
        subject_id="s1", arm_id="a1", worker_repeat=0, realization_ref="sha256:" + "0" * 64
    )


class _HangingHandle:
    """Simulates a live bridge/container process that never finishes on its own."""

    def __init__(self) -> None:
        self.teardown_called = False
        self.teardown_started = asyncio.Event()

    def run(self) -> BridgeTrialResult:
        import time

        # Block the worker thread indefinitely; only cancellation + our own
        # teardown call ever ends this trial, mirroring a stuck container.
        while not self.teardown_called:
            time.sleep(0.01)
        raise RuntimeError("trial cancelled")

    def teardown(self) -> None:
        self.teardown_called = True


class _CancellingBridge:
    def __init__(self) -> None:
        self.created: list[PierExchange] = []
        self.handle: _HangingHandle | None = None

    def create(self, *, exchange: PierExchange, package: Mapping[str, str]) -> PierBridgeHandle:
        self.created.append(exchange)
        self.handle = _HangingHandle()
        return self.handle


class _NeverCreatedBridge:
    """A bridge whose ``create`` must never be called once admission has stopped."""

    def __init__(self) -> None:
        self.created: list[PierExchange] = []

    def create(self, *, exchange: PierExchange, package: Mapping[str, str]) -> PierBridgeHandle:
        self.created.append(exchange)
        raise AssertionError("bridge.create must not be called after admission stops")


def _adapter(tmp_path: Path, bridge: Any) -> PierAdapter:
    store = ObjectStore(tmp_path / ".assay")
    return PierAdapter(
        store=store,
        bridge=bridge,
        binding=_binding(),
        model_route={"model": "anthropic/claude-3-haiku", "provider": "amazon-bedrock"},
        trial_limits={"cpu": 1, "memory_mb": 512, "timeout_s": 60},
    )


async def test_cancellation_tears_down_the_bridge_handle_within_the_bounded_window(
    tmp_path: Path,
) -> None:
    bridge = _CancellingBridge()
    adapter = _adapter(tmp_path, bridge)
    task = asyncio.create_task(
        adapter.run_cell(
            input_value={"task": "do it", "repository": {"a.py": "x = 1\n"}},
            coordinate=_coordinate(),
        )
    )
    await asyncio.sleep(0.05)  # let run_cell reach bridge.create() and start handle.run()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert bridge.handle is not None
    assert bridge.handle.teardown_called, "cancellation must tear the bridge handle down"


async def test_cancellation_leaves_no_orphan_bridge_handle(tmp_path: Path) -> None:
    """Every handle this adapter creates is torn down, cancelled or not."""
    bridge = _CancellingBridge()
    adapter = _adapter(tmp_path, bridge)
    task = asyncio.create_task(
        adapter.run_cell(
            input_value={"task": "do it", "repository": {"a.py": "x = 1\n"}},
            coordinate=_coordinate(),
        )
    )
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(bridge.created) == 1
    assert bridge.handle is not None and bridge.handle.teardown_called


async def test_admission_stops_before_dispatch_reports_unavailable_accounting(
    tmp_path: Path,
) -> None:
    """A cell that never reaches the bridge (admission already stopped) is
    unavailable, not uncertain: no attempt was ever dispatched for it."""
    bridge = _NeverCreatedBridge()
    adapter = _adapter(tmp_path, bridge)
    result = await adapter.run_cell(
        input_value={"task": "", "repository": {}}, coordinate=_coordinate()
    )
    assert isinstance(result, WorkerFailure)
    assert result.accounting == Accounting()
    assert bridge.created == []


async def test_cancellation_preserves_partial_evidence_reachability(tmp_path: Path) -> None:
    """A run_cell that raises mid-flight (not cancelled) still surfaces uncertain,
    never zero, accounting -- the codebase's own accounting invariant."""
    store = ObjectStore(tmp_path / ".assay")

    class _FailingHandle:
        def run(self) -> BridgeTrialResult:
            raise RuntimeError("bridge connection dropped mid-trial")

        def teardown(self) -> None:
            pass

    class _FailingBridge:
        def create(self, *, exchange: PierExchange, package: Mapping[str, str]) -> PierBridgeHandle:
            return _FailingHandle()

    adapter = PierAdapter(
        store=store,
        bridge=_FailingBridge(),
        binding=_binding(),
        model_route={"model": "anthropic/claude-3-haiku", "provider": "amazon-bedrock"},
        trial_limits={"cpu": 1, "memory_mb": 512, "timeout_s": 60},
    )
    result = await adapter.run_cell(
        input_value={"task": "do it", "repository": {"a.py": "x = 1\n"}}, coordinate=_coordinate()
    )
    assert isinstance(result, WorkerFailure)
    assert result.accounting.coverage == "uncertain"
    assert result.accounting.amount is None


async def test_execution_cancellation_persists_exact_missing_coordinates(tmp_path: Path) -> None:
    """Cancelling a V2 run mid-flight, through the Pier adapter, must persist
    the exact missing cell coordinates and no orphaned bridge handle."""
    store = ObjectStore(tmp_path / ".assay")
    bridge = _CancellingBridge()
    adapter = _adapter(Path(store.root), bridge)

    def publish(value: Any) -> str:
        return str(store.publish_json(value))

    subjects = (
        Subject(
            id="s1",
            label="s1",
            digest=publish({"s": "s1"}),
            partition="t",
            payload_ref=publish({"s": "s1"}),
        ),
    )
    arms = (Arm(id="a1", worker=adapter.configuration("a1"), intervention={}),)
    realizations = (
        Realization(
            subject_id="s1",
            arm_id="a1",
            digest=publish({"task": "do it", "repository": {"a.py": "x = 1\n"}}),
            artifact_ref=publish({"task": "do it", "repository": {"a.py": "x = 1\n"}}),
        ),
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
        "$id": "https://assay.test/pier-cancellation-scalar.schema.json",
        "allOf": [
            {"$ref": "https://paa.dev/paa-evidence-record.schema.json"},
            {"properties": {"verdict": {"properties": {"value": {"type": "number"}}}}},
        ],
    }
    evaluator = EvaluatorDeclaration(
        id="quality",
        identity=identity,
        payload_schema=str(companion["$id"]),
        payload_schema_ref=publish(companion),
        configuration={},
        basis_ref=publish({"rubric": "quality-v1"}),
        repeats=1,
    )
    task = {
        "task": "pier_cancellation_fixture",
        "version": 1,
        "description": "Pier cancellation fixture",
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
    runtime = RuntimeProfile(
        id="pier", version="lock-v1", configuration_ref=publish({"runtime": "pier", "lock": "v1"})
    )
    plan = compile_plan_v2(
        snapshot,
        snapshot_ref=publish(snapshot.model_dump(mode="json")),
        worker_repeats=1,
        runtime=runtime,
    )
    plan_bytes = canonical_json(plan.model_dump(mode="json"))

    class _FakeEvaluator:
        def configuration(self) -> dict[str, Any]:
            return {}

        async def evaluate(
            self, *, input_value: Any, output: Any, coordinate: Any
        ) -> EvaluationSuccess:
            return EvaluationSuccess(1.0)

    arguments: dict[str, Any] = {
        "plan_bytes": plan_bytes,
        "authorization": digest_bytes(plan_bytes),
        "snapshot": snapshot,
        "store": store,
        "workers": {"a1": adapter},
        "evaluators": {"quality": _FakeEvaluator()},
    }

    running = asyncio.create_task(execute_plan(**arguments))
    await asyncio.sleep(0.05)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running

    assert bridge.handle is not None and bridge.handle.teardown_called

    manifests = []
    for path in store.objects.iterdir():
        try:
            value = json.loads(path.read_bytes())
        except (OSError, ValueError):
            continue
        if isinstance(value, dict) and value.get("schema_version") == "assay-run-manifest/0.1.0":
            manifests.append(value)
    assert len(manifests) == 1
    manifest = manifests[0]
    assert manifest["status"] == "incomplete"
    assert manifest["missing_coordinates"] == ["s1:a1:w0", "s1:a1:w0:quality:e0"]
