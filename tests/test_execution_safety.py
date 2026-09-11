from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from jig import AgentConfig
from test_execution import FakeEvaluator, FakeWorker, execution_fixture

from assay.adapters.jig import JigWorker
from assay.canonical import canonical_json, digest_bytes
from assay.execution import (
    Accounting,
    EvaluationSuccess,
    RunFailed,
    RunSucceeded,
    WorkerFailure,
    WorkerSuccess,
    execute_plan,
)
from assay.store import ObjectStore


@pytest.mark.parametrize("drift", ["worker", "evaluator", "concurrency", "preparation", "task"])
async def test_preflight_rejects_drift_before_any_calls(tmp_path: Any, drift: str) -> None:
    fixture = execution_fixture(ObjectStore(tmp_path))
    arguments = fixture.arguments
    calls = []

    class CountingWorker(FakeWorker):
        def configuration(self, arm_id: str) -> dict[str, Any]:
            config = super().configuration(arm_id)
            return {**config, "model": "unapproved"} if drift == "worker" else config

        async def run(self, *, input_value: Any, arm_id: str) -> WorkerSuccess:
            calls.append(arm_id)
            return WorkerSuccess("unexpected")

    class ChangedEvaluator(FakeEvaluator):
        def configuration(self) -> dict[str, Any]:
            return {"version": "changed"}

    arguments["workers"] = {arm.id: CountingWorker() for arm in fixture.snapshot.arms}
    if drift == "evaluator":
        arguments["evaluators"] = {"quality": ChangedEvaluator()}
    if drift == "concurrency":
        arguments["concurrency"] = 99
    if drift == "preparation":
        plan = json.loads(fixture.plan_bytes)
        plan["preparation_mode"] = "authorized"
        arguments["plan_bytes"] = canonical_json(plan)
        arguments["authorization"] = digest_bytes(arguments["plan_bytes"])
    if drift == "task":
        fixture.store._path(fixture.snapshot.paa_task_ref).unlink()
    result = await execute_plan(**arguments)
    assert isinstance(result, RunFailed), result
    assert calls == []


async def test_distinct_runs_have_distinct_records_and_correct_worker_config(tmp_path: Any) -> None:
    fixture = execution_fixture(ObjectStore(tmp_path), subject_ids=("ok",))
    first = await execute_plan(**fixture.arguments)
    second = await execute_plan(**fixture.arguments)
    assert isinstance(first, RunSucceeded) and isinstance(second, RunSucceeded)
    assert first.manifest.run_id != second.manifest.run_id
    assert not set(first.manifest.execution_records.values()) & set(
        second.manifest.execution_records.values()
    )
    assert not set(first.manifest.evaluation_records.values()) & set(
        second.manifest.evaluation_records.values()
    )
    record_ref = next(iter(first.manifest.evaluation_records.values()))
    record = json.loads(fixture.store.read_bytes(record_ref))
    assert record["worker"]["configuration_ref"] == digest_bytes(
        canonical_json(FakeWorker().configuration("candidate"))
    )


async def test_invalid_verdict_is_failure_and_keeps_attempt_usage(tmp_path: Any) -> None:
    fixture = execution_fixture(ObjectStore(tmp_path), subject_ids=("ok",), worker_repeats=1)

    class InvalidEvaluator(FakeEvaluator):
        async def evaluate(self, **kwargs: Any) -> EvaluationSuccess:
            return EvaluationSuccess(
                12,
                accounting=Accounting(
                    usage={"output_tokens": 11},
                    amount=0.2,
                    currency="USD",
                    coverage="estimated",
                    basis="test-rates-v1",
                ),
            )

    arguments = fixture.arguments
    arguments["evaluators"] = {"quality": InvalidEvaluator()}
    result = await execute_plan(**arguments)
    assert isinstance(result, RunSucceeded), result
    for ref in result.manifest.evaluation_records.values():
        record = json.loads(fixture.store.read_bytes(ref))
        assert record["error_type"] == "InvalidVerdict"
    operating = [
        json.loads(fixture.store.read_bytes(ref))
        for key, ref in result.manifest.operating_records.items()
        if key.startswith("evaluator:")
    ]
    assert len(operating) == 4
    assert all(record["usage"] == {"output_tokens": 11} for record in operating)
    assert all(record["price"]["amount"] == 0.2 for record in operating)


async def test_failed_attempt_preserves_trace_usage_and_unavailable_price(tmp_path: Any) -> None:
    fixture = execution_fixture(ObjectStore(tmp_path), subject_ids=("ok",), worker_repeats=1)

    class Failure(FakeWorker):
        async def run(self, **kwargs: Any) -> WorkerFailure:
            return WorkerFailure(
                "Timeout",
                "provider timed out",
                trace={"trace_id": "failed"},
                accounting=Accounting(usage={"input_tokens": 23}),
            )

    arguments = fixture.arguments
    arguments["workers"] = {arm.id: Failure() for arm in fixture.snapshot.arms}
    result = await execute_plan(**arguments)
    assert isinstance(result, RunSucceeded), result
    for ref in result.manifest.execution_records.values():
        record = json.loads(fixture.store.read_bytes(ref))
        assert json.loads(fixture.store.read_bytes(record["trace_ref"])) == {"trace_id": "failed"}
    assert len(result.manifest.operating_records) == 2
    for ref in result.manifest.operating_records.values():
        record = json.loads(fixture.store.read_bytes(ref))
        assert record["usage"] == {"input_tokens": 23}
        assert record["price"] is None
        sources = [
            json.loads(fixture.store.read_bytes(source)) for source in record["source_references"]
        ]
        assert any(source.get("coverage") == "unavailable" for source in sources)


async def test_disk_failure_stops_dispatch_and_drains_started_work(tmp_path: Any) -> None:
    fixture = execution_fixture(
        ObjectStore(tmp_path), subject_ids=("ok",), worker_repeats=4, concurrency=2
    )
    arguments = fixture.arguments
    started = 0
    finished = 0
    two_started = asyncio.Event()
    failure_written = asyncio.Event()

    class SlowWorker(FakeWorker):
        async def run(self, **kwargs: Any) -> WorkerSuccess:
            nonlocal started, finished
            started += 1
            my_index = started
            if started == 2:
                two_started.set()
            await two_started.wait()
            if my_index == 2:
                await failure_written.wait()
            finished += 1
            return WorkerSuccess({"score": 1})

    original = fixture.store.publish_json

    def fail_first_outcome(value: Any) -> Any:
        if (
            isinstance(value, dict)
            and value.get("schema_version") == "assay-execution-outcome/0.1.0"
            and not failure_written.is_set()
        ):
            failure_written.set()
            raise OSError("disk full")
        return original(value)

    fixture.store.publish_json = fail_first_outcome  # type: ignore[method-assign]
    arguments["workers"] = {arm.id: SlowWorker() for arm in fixture.snapshot.arms}
    result = await asyncio.wait_for(execute_plan(**arguments), timeout=3)
    assert isinstance(result, RunFailed), result
    assert result.error_type == "OSError"
    assert started == finished == 2
    assert result.manifest is not None and result.manifest.status == "incomplete"
    assert len(result.manifest.execution_records) == 1
    assert result.manifest.evaluation_records == {}
    assert result.manifest_ref is not None


async def test_final_manifest_failure_returns_completed_refs(tmp_path: Any) -> None:
    fixture = execution_fixture(ObjectStore(tmp_path), subject_ids=("ok",), worker_repeats=1)
    original = fixture.store.publish_json

    def fail_manifest(value: Any) -> Any:
        if isinstance(value, dict) and value.get("schema_version") == "assay-run-manifest/0.1.0":
            raise OSError("manifest write failed")
        return original(value)

    fixture.store.publish_json = fail_manifest  # type: ignore[method-assign]
    result = await execute_plan(**fixture.arguments)
    assert isinstance(result, RunFailed)
    assert result.manifest is not None
    assert len(result.manifest.execution_records) == 2
    assert len(result.manifest.evaluation_records) == 4
    assert result.manifest_ref is None


async def test_cancellation_awaits_worker_cleanup(tmp_path: Any) -> None:
    fixture = execution_fixture(ObjectStore(tmp_path), concurrency=2)
    arguments = fixture.arguments
    started = asyncio.Event()
    cleaned = 0

    class BlockingWorker(FakeWorker):
        async def run(self, **kwargs: Any) -> WorkerSuccess:
            nonlocal cleaned
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                cleaned += 1
            raise AssertionError("unreachable")

    arguments["workers"] = {arm.id: BlockingWorker() for arm in fixture.snapshot.arms}
    running = asyncio.create_task(execute_plan(**arguments))
    await started.wait()
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert cleaned == 2


async def test_jig_failure_is_typed_and_input_is_not_coerced(monkeypatch: Any) -> None:
    calls: list[str] = []

    async def fake_run(config: Any, prompt: str) -> Any:
        calls.append(prompt)
        return SimpleNamespace(
            output="termination text",
            parsed=None,
            trace_id="t1",
            grading=None,
            duration_ms=3,
            error=RuntimeError("failed"),
            usage={"total_input_tokens": 9, "total_cost": 0},
        )

    monkeypatch.setattr("assay.adapters.jig.run_agent", fake_run)
    worker = JigWorker(configs={"a": SimpleNamespace()}, version="test")
    failure = await worker.run(input_value="exact prompt", arm_id="a")
    assert isinstance(failure, WorkerFailure)
    assert failure.error_type == "RuntimeError"
    assert failure.trace["trace_id"] == "t1"
    assert failure.accounting.usage == {"input_tokens": 9}
    assert failure.accounting.amount is None
    bad_input = await worker.run(input_value={"prompt": "changed"}, arm_id="a")
    assert isinstance(bad_input, WorkerFailure) and bad_input.error_type == "InvalidInput"
    assert calls == ["exact prompt"]


async def test_jig_preserves_native_structured_output(monkeypatch: Any) -> None:
    # A native structured result is returned as JSON data, not discarded in favor
    # of Jig's textual output marker.
    async def fake_run(config: Any, prompt: str) -> Any:
        return SimpleNamespace(
            output="marker",
            parsed={"answer": 42},
            trace_id="t1",
            grading=None,
            duration_ms=3,
            error=None,
            usage={"llm_calls": 1},
        )

    monkeypatch.setattr("assay.adapters.jig.run_agent", fake_run)
    result = await JigWorker(configs={"a": SimpleNamespace()}, version="test").run(
        input_value="prompt", arm_id="a"
    )
    assert isinstance(result, WorkerSuccess) and result.output == {"answer": 42}


def test_jig_configuration_tracks_live_prompt_and_resource_settings() -> None:
    class Resource:
        def __init__(self) -> None:
            self.model = "model-v1"

        def configuration(self) -> dict[str, Any]:
            return {"model": self.model, "revision": "123"}

    resource = Resource()
    config = AgentConfig(
        name="fixture",
        description="",
        system_prompt="prompt-v1",
        llm=resource,
        feedback=resource,
        tracer=resource,
        tools=resource,
    )
    worker = JigWorker(configs={"a": config}, version="1")
    original = canonical_json(worker.configuration("a"))
    resource.model = "model-v2"
    assert original != canonical_json(worker.configuration("a"))
    resource.model = "model-v1"
    worker.configs = {"a": config.with_(system_prompt="prompt-v2")}
    assert original != canonical_json(worker.configuration("a"))
    worker.configs = {"a": config.with_(system_prompt=lambda: "dynamic")}
    with pytest.raises(ValueError, match="static system prompt"):
        worker.configuration("a")
    worker.configs = {"a": config.with_(llm=object())}
    with pytest.raises(ValueError, match="stable configuration"):
        worker.configuration("a")


async def test_bad_worker_payload_is_cell_failure_preserving_accounting(tmp_path: Any) -> None:
    fixture = execution_fixture(ObjectStore(tmp_path), subject_ids=("ok",), worker_repeats=2)

    class MalformedWorker(FakeWorker):
        async def run(self, **kwargs: Any) -> WorkerSuccess:
            return WorkerSuccess(
                object(),
                trace={"trace_id": "bad-output"},
                accounting=Accounting(usage={"llm_calls": 1}),
            )

    arguments = fixture.arguments
    arguments["workers"] = {arm.id: MalformedWorker() for arm in fixture.snapshot.arms}
    result = await execute_plan(**arguments)
    assert isinstance(result, RunSucceeded), result
    assert len(result.manifest.execution_records) == 4
    for ref in result.manifest.execution_records.values():
        record = json.loads(fixture.store.read_bytes(ref))
        assert record["status"] == "failed" and record["error_type"] == "CanonicalizationError"
        assert json.loads(fixture.store.read_bytes(record["trace_ref"])) == {
            "trace_id": "bad-output"
        }
    for ref in result.manifest.operating_records.values():
        assert json.loads(fixture.store.read_bytes(ref))["usage"] == {"llm_calls": 1}


async def test_evaluator_configuration_drift_between_repeats_skips_changed_call(
    tmp_path: Any,
) -> None:
    fixture = execution_fixture(
        ObjectStore(tmp_path),
        subject_ids=("ok",),
        worker_repeats=1,
        evaluator_repeats=2,
        concurrency=1,
    )

    class MutableEvaluator(FakeEvaluator):
        calls = 0

        def configuration(self) -> dict[str, Any]:
            return super().configuration() if self.calls == 0 else {"version": "changed"}

        async def evaluate(self, **kwargs: Any) -> EvaluationSuccess:
            self.calls += 1
            return EvaluationSuccess(0.5)

    evaluator = MutableEvaluator()
    arguments = fixture.arguments
    arguments["evaluators"] = {"quality": evaluator}
    result = await execute_plan(**arguments)
    assert isinstance(result, RunSucceeded), result
    assert evaluator.calls == 1
    records = [
        json.loads(fixture.store.read_bytes(ref))
        for ref in result.manifest.evaluation_records.values()
    ]
    assert sum(record.get("error_type") == "ValueError" for record in records) == 3
