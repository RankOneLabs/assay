from __future__ import annotations

import json
from typing import Any

import pytest
from test_execution import FakeEvaluator, FakeWorker, execution_fixture
from test_execution_safety import _ceiling_plan

from assay.canonical import digest_bytes
from assay.execution import (
    Accounting,
    AdmissionLedger,
    EvaluationFailed,
    RunSucceeded,
    WorkerFailure,
    execute_plan,
)
from assay.store import ObjectStore


def test_accounting_rejects_unknown_coverage() -> None:
    with pytest.raises(ValueError, match="unknown price coverage"):
        Accounting(coverage="bogus")  # type: ignore[arg-type]


def test_accounting_permits_uncertain_with_no_price() -> None:
    accounting = Accounting(coverage="uncertain", usage={"input_tokens": 3})
    assert accounting.amount is None
    assert accounting.currency is None


def test_accounting_rejects_priced_uncertain_attempt() -> None:
    with pytest.raises(ValueError, match="available price requires"):
        Accounting(amount=1.0, currency="USD", basis="rates-v1", coverage="uncertain")


def test_accounting_rejects_priced_unavailable_attempt() -> None:
    with pytest.raises(ValueError, match="available price requires"):
        Accounting(amount=1.0, currency="USD", basis="rates-v1", coverage="unavailable")


async def test_unattempted_cell_is_unavailable_not_uncertain(tmp_path: Any) -> None:
    # Configuration drift is caught before the worker is ever invoked: no
    # usage was possible, so this is a genuine "no cost", not an unknown one.
    fixture = execution_fixture(ObjectStore(tmp_path), subject_ids=("ok",), worker_repeats=1)

    class DriftingWorker(FakeWorker):
        calls = 0

        def configuration(self, arm_id: str) -> dict[str, Any]:
            self.calls += 1
            return super().configuration(arm_id) if self.calls == 1 else {"drifted": True}

    arguments = fixture.arguments
    arguments["workers"] = {arm.id: DriftingWorker() for arm in fixture.snapshot.arms}
    result = await execute_plan(**arguments)
    assert isinstance(result, RunSucceeded), result
    operating = [
        json.loads(fixture.store.read_bytes(ref))
        for key, ref in result.manifest.operating_records.items()
        if key.startswith("worker:")
    ]
    coverages = set()
    for record in operating:
        for source in record["source_references"]:
            detail = json.loads(fixture.store.read_bytes(source))
            if "coverage" in detail:
                coverages.add(detail["coverage"])
    assert coverages == {"unavailable"}


async def test_worker_call_that_raises_before_returning_is_uncertain_not_unavailable(
    tmp_path: Any,
) -> None:
    # The adapter was genuinely invoked and failed before reporting usage: the
    # cost is unknown, and must never be collapsed into "no cost" (unavailable).
    fixture = execution_fixture(ObjectStore(tmp_path), subject_ids=("ok",), worker_repeats=1)

    class RaisingWorker(FakeWorker):
        async def run(self, **kwargs: Any) -> Any:
            raise RuntimeError("connection reset before any usage was reported")

    arguments = fixture.arguments
    arguments["workers"] = {arm.id: RaisingWorker() for arm in fixture.snapshot.arms}
    result = await execute_plan(**arguments)
    assert isinstance(result, RunSucceeded), result
    for ref in result.manifest.execution_records.values():
        record = json.loads(fixture.store.read_bytes(ref))
        assert record["error_type"] == "RuntimeError"
    for key, ref in result.manifest.operating_records.items():
        if not key.startswith("worker:"):
            continue
        record = json.loads(fixture.store.read_bytes(ref))
        assert record["price"] is None
        coverages = {
            json.loads(fixture.store.read_bytes(source))["coverage"]
            for source in record["source_references"]
            if "coverage" in json.loads(fixture.store.read_bytes(source))
        }
        assert coverages == {"uncertain"}


async def test_evaluator_call_that_raises_before_returning_is_uncertain(tmp_path: Any) -> None:
    fixture = execution_fixture(
        ObjectStore(tmp_path), subject_ids=("ok",), worker_repeats=1, evaluator_repeats=1
    )

    class RaisingEvaluator(FakeEvaluator):
        async def evaluate(self, **kwargs: Any) -> Any:
            raise RuntimeError("evaluator backend unreachable")

    arguments = fixture.arguments
    arguments["evaluators"] = {"quality": RaisingEvaluator()}
    result = await execute_plan(**arguments)
    assert isinstance(result, RunSucceeded), result
    evaluator_operating = [
        (key, ref)
        for key, ref in result.manifest.operating_records.items()
        if key.startswith("evaluator:")
    ]
    assert evaluator_operating
    for _key, ref in evaluator_operating:
        record = json.loads(fixture.store.read_bytes(ref))
        for source in record["source_references"]:
            detail = json.loads(fixture.store.read_bytes(source))
            if "coverage" in detail:
                assert detail["coverage"] == "uncertain"


def test_worker_failure_default_accounting_is_unavailable() -> None:
    assert WorkerFailure("SomeError", "message").accounting.coverage == "unavailable"


def test_evaluation_failed_default_accounting_is_unavailable() -> None:
    assert EvaluationFailed("SomeError", "message").accounting.coverage == "unavailable"


def _operating_coverages(store: ObjectStore, record_ref: str) -> set[str]:
    record = json.loads(store.read_bytes(record_ref))
    return {
        detail["coverage"]
        for source in record["source_references"]
        if "coverage" in (detail := json.loads(store.read_bytes(source)))
    }


async def test_pre_dispatch_wall_refusal_has_unavailable_accounting(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = execution_fixture(ObjectStore(tmp_path), subject_ids=("ok",), worker_repeats=1)
    plan_bytes = _ceiling_plan(
        fixture, max_cells=2, max_wall_time_seconds=30, max_fleet_occupancy=1
    )
    expired = False
    original_remaining = AdmissionLedger.remaining_seconds

    class ExpiringWorker(FakeWorker):
        calls = 0

        def configuration(self, arm_id: str) -> dict[str, Any]:
            nonlocal expired
            self.calls += 1
            if self.calls > 1:
                expired = True
            return super().configuration(arm_id)

    def remaining(ledger: AdmissionLedger) -> float | None:
        return -1 if expired else original_remaining(ledger)

    monkeypatch.setattr(AdmissionLedger, "remaining_seconds", remaining)
    result = await execute_plan(**{
        **fixture.arguments,
        "plan_bytes": plan_bytes,
        "authorization": digest_bytes(plan_bytes),
        "workers": {arm.id: ExpiringWorker() for arm in fixture.snapshot.arms},
    })
    assert result.manifest is not None
    worker_records = [ref for key, ref in result.manifest.operating_records.items()
                      if key.startswith("worker:")]
    assert worker_records
    assert all(_operating_coverages(fixture.store, ref) == {"unavailable"}
               for ref in worker_records)


async def test_dispatched_evaluation_timeout_has_uncertain_accounting(tmp_path: Any) -> None:
    fixture = execution_fixture(
        ObjectStore(tmp_path), subject_ids=("ok",), worker_repeats=1, evaluator_repeats=1
    )

    class TimedOutEvaluator(FakeEvaluator):
        async def evaluate(self, **kwargs: Any) -> Any:
            raise TimeoutError("evaluation timed out")

    result = await execute_plan(**{
        **fixture.arguments, "evaluators": {"quality": TimedOutEvaluator()}
    })
    assert result.manifest is not None
    evaluator_records = [ref for key, ref in result.manifest.operating_records.items()
                         if key.startswith("evaluator:")]
    assert evaluator_records
    assert all(_operating_coverages(fixture.store, ref) == {"uncertain"}
               for ref in evaluator_records)
