from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import paa_contracts
import pytest

from assay.adapters.pier import BridgeTrialResult, PierAdapter, PierBridgeHandle
from assay.canonical import canonical_json, digest_bytes
from assay.execution import (
    EvaluationSuccess,
    RunSucceeded,
    WorkerFailure,
    WorkerSuccess,
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
from assay.pier_protocol import ArtifactEntry, ArtifactManifest, PierExchange, RuntimeBinding
from assay.planning import compile_plan_v2
from assay.store import ObjectStore

PER_CELL_USD = 0.72


def _binding(package_digest: str) -> RuntimeBinding:
    return RuntimeBinding(
        runtime_version="lock-v1",
        image_digest="sha256:" + "1" * 64,
        configuration_ref="sha256:" + "2" * 64,
        package_digest=package_digest,
    )


def _manifest_and_artifacts(exchange: PierExchange) -> tuple[ArtifactManifest, dict[str, bytes]]:
    """Build a manifest plus every declared artifact's bytes.

    The "manifest" kind entry points at a small, independent marker file --
    not the wire ``ArtifactManifest`` object's own serialized bytes, which
    would make the manifest describe itself (a checksum-of-itself fixed
    point with no stable solution).
    """
    contents = {
        "raw_trajectory.json": b'{"steps": []}',
        "candidate.txt": b"final answer",
        "result.json": b'{"passed": true}',
        "configuration.json": b'{"model": "x"}',
        "manifest_marker.json": b'{"manifest": "committed"}',
    }
    kinds = {
        "raw_trajectory.json": "raw_trajectory",
        "candidate.txt": "candidate",
        "result.json": "result",
        "configuration.json": "configuration",
        "manifest_marker.json": "manifest",
    }
    entries = tuple(
        ArtifactEntry(
            path=path,
            kind=kind,  # type: ignore[arg-type]
            size_bytes=len(contents[path]),
            checksum=digest_bytes(contents[path]),
            utf8=True,
        )
        for path, kind in kinds.items()
    )
    manifest = ArtifactManifest(
        exchange=exchange, entries=entries, aggregate_bytes=sum(e.size_bytes for e in entries)
    )
    manifest_bytes = canonical_json(manifest.model_dump(mode="json"))
    artifacts = {**contents, "manifest.json": manifest_bytes}
    return manifest, artifacts


class _Handle:
    def __init__(self, result: BridgeTrialResult) -> None:
        self._result = result
        self.torn_down = False

    def run(self) -> BridgeTrialResult:
        return self._result

    def teardown(self) -> None:
        self.torn_down = True


class _FixedBridge:
    """Always creates a handle bound to the exact exchange it was asked to run."""

    def __init__(self, *, usage: dict[str, float] | None, cost_key: str = "cost_usd") -> None:
        self.usage = usage
        self.cost_key = cost_key
        self.created: list[PierExchange] = []

    def create(self, *, exchange: PierExchange, package: dict[str, str]) -> PierBridgeHandle:
        self.created.append(exchange)
        _, artifacts = _manifest_and_artifacts(exchange)
        return _Handle(
            BridgeTrialResult(
                exchange=exchange,
                status="succeeded",
                exception_info=None,
                exit_status="Submitted",
                usage=self.usage,
                artifacts=artifacts,
            )
        )


def _adapter(tmp_path: Path, bridge: Any) -> PierAdapter:
    store = ObjectStore(tmp_path / ".assay")
    return PierAdapter(
        store=store,
        bridge=bridge,
        binding=_binding("sha256:" + "0" * 64),
        model_route={"model": "anthropic/claude-3-haiku", "provider": "amazon-bedrock"},
        trial_limits={"cpu": 1, "memory_mb": 512, "timeout_s": 60},
    )


def _coordinate(**overrides: object) -> CellCoordinate:
    fields: dict[str, object] = {
        "subject_id": "s1",
        "arm_id": "a1",
        "worker_repeat": 0,
        "realization_ref": "sha256:" + "0" * 64,
    }
    fields.update(overrides)
    return CellCoordinate(**fields)  # type: ignore[arg-type]


async def test_measured_accounting_reflects_bridge_usage_and_cost(tmp_path: Path) -> None:
    usage = {"prompt_tokens": 100, "completion_tokens": 50, "cost_usd": PER_CELL_USD}
    bridge = _FixedBridge(usage=usage)
    adapter = _adapter(tmp_path, bridge)
    result = await adapter.run_cell(
        input_value={"task": "do it", "repository": {"a.py": "x = 1\n"}}, coordinate=_coordinate()
    )
    assert isinstance(result, WorkerSuccess)
    assert result.accounting.coverage == "measured"
    assert result.accounting.amount == PER_CELL_USD
    assert result.accounting.currency == "USD"
    assert result.accounting.basis


async def test_uncertain_accounting_when_dispatched_without_usage(tmp_path: Path) -> None:
    bridge = _FixedBridge(usage=None)
    adapter = _adapter(tmp_path, bridge)
    result = await adapter.run_cell(
        input_value={"task": "do it", "repository": {"a.py": "x = 1\n"}}, coordinate=_coordinate()
    )
    assert isinstance(result, WorkerSuccess)
    assert result.accounting.coverage == "uncertain"
    assert result.accounting.amount is None


async def test_unavailable_accounting_when_never_dispatched(tmp_path: Path) -> None:
    bridge = _FixedBridge(usage=None)
    adapter = _adapter(tmp_path, bridge)
    result = await adapter.run_cell(
        input_value={"task": "", "repository": {}}, coordinate=_coordinate()
    )
    assert isinstance(result, WorkerFailure)
    assert result.accounting.coverage == "unavailable"
    assert result.accounting.amount is None
    assert bridge.created == []


class _FakeEvaluator:
    def configuration(self) -> dict[str, Any]:
        return {}

    async def evaluate(
        self, *, input_value: Any, output: Any, coordinate: Any
    ) -> EvaluationSuccess:
        return EvaluationSuccess(1.0)


def _pier_execution_fixture(store: ObjectStore, *, bridge: Any) -> tuple[bytes, dict[str, Any]]:
    """Two subjects x two arms, each cell priced at PER_CELL_USD -- mirrors the smoke scale."""

    def publish(value: Any) -> str:
        return str(store.publish_json(value))

    adapter = _adapter(Path(store.root), bridge)
    subjects = tuple(
        Subject(
            id=value,
            label=value,
            digest=publish({"s": value}),
            partition="test",
            payload_ref=publish({"s": value}),
        )
        for value in ("s1", "s2")
    )
    arms = tuple(
        Arm(id=value, worker=adapter.configuration(value), intervention={"kind": value})
        for value in ("reference", "candidate")
    )
    realizations = tuple(
        Realization(
            subject_id=subject.id,
            arm_id=arm.id,
            digest=publish({"task": "solve it", "repository": {"a.py": "x = 1\n"}}),
            artifact_ref=publish({"task": "solve it", "repository": {"a.py": "x = 1\n"}}),
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
        "$id": "https://assay.test/pier-scalar.schema.json",
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
        "task": "pier_fixture_quality",
        "version": 1,
        "description": "Pier accounting fixture",
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
    arguments = {
        "plan_bytes": plan_bytes,
        "authorization": digest_bytes(plan_bytes),
        "snapshot": snapshot,
        "store": store,
        "workers": {arm.id: adapter for arm in snapshot.arms},
        "evaluators": {"quality": _FakeEvaluator()},
    }
    return plan_bytes, arguments


async def test_total_cost_ties_to_per_cell_rate_across_the_grid(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / ".assay")
    bridge = _FixedBridge(usage={"cost_usd": PER_CELL_USD})
    _, arguments = _pier_execution_fixture(store, bridge=bridge)
    result = await execute_plan(**arguments)
    assert isinstance(result, RunSucceeded), result

    total = 0.0
    for ref in result.manifest.operating_records.values():
        record = json.loads(store.read_bytes(ref))
        if record["price"] is not None:
            total += record["price"]["amount"]
    cell_count = len(result.manifest.execution_records)
    assert cell_count == 4
    assert total == pytest.approx(cell_count * PER_CELL_USD)
    assert total == pytest.approx(2.88)  # smoke-scale grid: 4 cells * $0.72
