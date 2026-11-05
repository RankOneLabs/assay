"""Verified checkpoints retain terminal outcomes and never dispatch them again."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_execution import FakeEvaluator, FakeWorker, default_runtime, execution_fixture

import assay.execution as execution
from assay.canonical import canonical_json
from assay.execution import AdmissionHalt, RunFailed, RunSucceeded, execute_plan
from assay.models import ExecutionOutcome, ExecutionPlanV3, RunManifest, parse_execution_plan
from assay.planning import compile_plan_v2
from assay.store import ObjectStore
from assay.verify import verify_manifest


async def checkpoint_fixture(tmp_path: Path) -> tuple[Any, Any, str]:
    fixture = execution_fixture(
        ObjectStore(tmp_path), worker_repeats=1, evaluator_repeats=1, concurrency=1,
    )
    full = await execute_plan(**fixture.arguments)
    assert isinstance(full, RunSucceeded)
    plan = parse_execution_plan(json.loads(fixture.plan_bytes))
    kept = {cell.id for cell in plan.cells if cell.arm_id == "reference"}
    evaluations = {item.id for item in plan.evaluations if item.cell_id in kept}
    missing = set(full.manifest.missing_coordinates) | {
        cell.id for cell in plan.cells if cell.id not in kept
    } | {item.id for item in plan.evaluations if item.id not in evaluations}
    partial = full.manifest.model_copy(update={
        "status": "incomplete", "missing_coordinates": tuple(sorted(missing)),
        "execution_records": {k: v for k, v in full.manifest.execution_records.items()
                              if k in kept},
        "evaluation_records": {k: v for k, v in full.manifest.evaluation_records.items()
                               if k in evaluations},
        "operating_records": {k: v for k, v in full.manifest.operating_records.items()
                              if k in {f"worker:{x}" for x in kept}
                              | {f"evaluator:{x}" for x in evaluations}},
    })
    ref = str(fixture.store.publish_json(partial.model_dump(mode="json")))
    assert [f.code for f in verify_manifest(fixture.store, ref)] == ["incomplete_run"]
    return fixture, partial, ref


async def test_resume_keeps_success_failure_grades_and_accounting_without_redispatch(
    tmp_path: Path,
) -> None:
    fixture, partial, ref = await checkpoint_fixture(tmp_path)
    called: list[tuple[str, str]] = []
    graded: list[str] = []

    class RemainingWorker(FakeWorker):
        async def run(self, *, input_value: Any, arm_id: str) -> Any:
            assert arm_id == "candidate"
            called.append((input_value["subject"], arm_id))
            return await super().run(input_value=input_value, arm_id=arm_id)

    class RemainingEvaluator(FakeEvaluator):
        async def evaluate(self, **kwargs: Any) -> Any:
            assert kwargs["coordinate"].id not in partial.evaluation_records
            graded.append(kwargs["coordinate"].id)
            return await super().evaluate(**kwargs)

    arguments = fixture.arguments
    arguments["workers"] = {arm.id: RemainingWorker() for arm in fixture.snapshot.arms}
    arguments["evaluators"] = {"quality": RemainingEvaluator()}
    result = await execute_plan(**arguments, resume_from=ref)
    assert isinstance(result, RunSucceeded), result
    assert len(called) == 2 and len(graded) == 1
    assert result.manifest.run_id == partial.run_id
    assert len(result.manifest.execution_records) == 4
    for field in ("execution_records", "evaluation_records", "operating_records"):
        assert getattr(partial, field).items() <= getattr(result.manifest, field).items()
    failed = [ExecutionOutcome.model_validate_json(fixture.store.read_bytes(v))
              for v in result.manifest.execution_records.values()]
    assert sum(item.status == "failed" for item in failed) == 2
    assert [f.code for f in verify_manifest(fixture.store, str(result.manifest_ref))] == [
        "incomplete_run",
    ]
    again = await execute_plan(**arguments, resume_from=str(result.manifest_ref))
    assert isinstance(again, RunSucceeded)
    assert len(called) == 2 and len(graded) == 1
    assert again.manifest_ref == result.manifest_ref


@pytest.mark.parametrize("corruption", ["plan", "coordinate", "missing_object"])
async def test_resume_refuses_invalid_checkpoints_before_dispatch(
    tmp_path: Path, corruption: str,
) -> None:
    fixture, partial, ref = await checkpoint_fixture(tmp_path)
    if corruption == "plan":
        partial = partial.model_copy(update={"plan_ref": "sha256:" + "f" * 64})
        ref = str(fixture.store.publish_json(partial.model_dump(mode="json")))
    elif corruption == "coordinate":
        key, value = next(iter(partial.execution_records.items()))
        outcome = json.loads(fixture.store.read_bytes(value))
        outcome["coordinate"]["worker_repeat"] = 900
        bad = str(fixture.store.publish_json(outcome))
        partial = partial.model_copy(update={
            "execution_records": {**partial.execution_records, key: bad},
        })
        ref = str(fixture.store.publish_json(partial.model_dump(mode="json")))
    else:
        fixture.store._path(next(iter(partial.execution_records.values()))).unlink()

    class NeverWorker(FakeWorker):
        async def run(self, **kwargs: Any) -> Any:
            pytest.fail("invalid checkpoint dispatched a worker")

    arguments = fixture.arguments
    arguments["workers"] = {arm.id: NeverWorker() for arm in fixture.snapshot.arms}
    result = await execute_plan(**arguments, resume_from=ref)
    assert isinstance(result, RunFailed)
    assert result.manifest_ref is None


def clock_ahead(seconds: int) -> type[datetime]:
    class AheadClock(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return datetime.now(tz) + timedelta(seconds=seconds)

    return AheadClock


@pytest.mark.parametrize("limit", ["cells", "wall"])
async def test_resume_does_not_reset_authorized_v3_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit: str,
) -> None:
    fixture = execution_fixture(
        ObjectStore(tmp_path), subject_ids=("ok",), worker_repeats=1, evaluator_repeats=1,
        concurrency=1,
    )
    base = compile_plan_v2(
        fixture.snapshot,
        snapshot_ref=str(fixture.store.publish_json(fixture.snapshot.model_dump(mode="json"))),
        worker_repeats=1, runtime=default_runtime(fixture.store), concurrency=1,
    )
    plan = ExecutionPlanV3.model_validate({
        **base.model_dump(mode="json"), "schema_version": "assay-execution-plan/0.3.0",
        "ceiling": {"max_cells": 1 if limit == "cells" else 2,
                    "max_wall_time_seconds": 60, "max_fleet_occupancy": 1},
    })
    fixture.plan_bytes = canonical_json(plan.model_dump(mode="json"))
    calls = []

    class CountWorker(FakeWorker):
        async def run(self, **kwargs: Any) -> Any:
            calls.append(kwargs)
            if limit == "wall":
                # The attempt itself consumes the allowance: it finishes 120s after it began.
                monkeypatch.setattr("assay.execution.datetime", clock_ahead(120))
                raise AdmissionHalt("billing_uncertain", "pause before the next cell")
            return await super().run(**kwargs)

    arguments = fixture.arguments
    arguments["workers"] = {arm.id: CountWorker() for arm in fixture.snapshot.arms}
    first = await execute_plan(**arguments)
    assert isinstance(first, RunFailed) and first.manifest_ref is not None
    assert len(calls) == 1
    resumed = await execute_plan(**arguments, resume_from=str(first.manifest_ref))
    assert isinstance(resumed, RunFailed)
    assert "ceiling" in resumed.message or "wall time" in resumed.message
    assert len(calls) == 1
    assert resumed.manifest is not None
    assert resumed.manifest.execution_records == first.manifest.execution_records


def v3_fixture(tmp_path: Path) -> Any:
    fixture = execution_fixture(
        ObjectStore(tmp_path), subject_ids=("ok",), worker_repeats=1, evaluator_repeats=1,
        concurrency=1,
    )
    base = compile_plan_v2(
        fixture.snapshot,
        snapshot_ref=str(fixture.store.publish_json(fixture.snapshot.model_dump(mode="json"))),
        worker_repeats=1, runtime=default_runtime(fixture.store), concurrency=1,
    )
    plan = ExecutionPlanV3.model_validate({
        **base.model_dump(mode="json"), "schema_version": "assay-execution-plan/0.3.0",
        "ceiling": {"max_cells": 2, "max_wall_time_seconds": 600, "max_fleet_occupancy": 1},
    })
    fixture.plan_bytes = canonical_json(plan.model_dump(mode="json"))
    return fixture


def published_manifests(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """A cancelled run publishes its manifest without returning the reference."""
    refs: list[str] = []
    publish = ObjectStore.publish_json

    def recording(self: ObjectStore, value: Any) -> Any:
        ref = publish(self, value)
        if isinstance(value, dict) and value.get("schema_version") == "assay-run-manifest/0.1.0":
            refs.append(str(ref))
        return ref

    monkeypatch.setattr(ObjectStore, "publish_json", recording)
    return refs


async def test_resume_pause_does_not_consume_the_wall_allowance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = v3_fixture(tmp_path)
    calls: list[str] = []

    class HaltOnceWorker(FakeWorker):
        async def run(self, *, input_value: Any, arm_id: str) -> Any:
            calls.append(arm_id)
            if len(calls) == 1:
                raise AdmissionHalt("billing_uncertain", "pause before the next cell")
            return await super().run(input_value=input_value, arm_id=arm_id)

    arguments = fixture.arguments
    arguments["workers"] = {arm.id: HaltOnceWorker() for arm in fixture.snapshot.arms}
    first = await execute_plan(**arguments)
    assert isinstance(first, RunFailed) and first.manifest_ref is not None
    assert len(calls) == 1
    monkeypatch.setattr("assay.execution.datetime", clock_ahead(7200))  # allowance is 600s
    resumed = await execute_plan(**arguments, resume_from=str(first.manifest_ref))
    assert isinstance(resumed, RunSucceeded), resumed
    assert len(calls) == 2


def test_active_seconds_counts_overlapping_work_once() -> None:
    def span(start: str, end: str) -> Any:
        return SimpleNamespace(started_at=f"2026-11-04T{start}Z", completed_at=f"2026-11-04T{end}Z")

    manifest: Any = SimpleNamespace(operating_records={})
    outcomes = [span("00:00:00", "00:00:10"), span("00:00:05", "00:00:20"),
                span("00:00:06", "00:00:07"), span("01:00:00", "01:00:30")]
    store: Any = None
    assert execution._active_seconds(store, manifest, outcomes) == 50


async def cancel_when(run: asyncio.Task[Any], entered: asyncio.Event) -> None:
    await entered.wait()
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run


async def test_resume_refuses_a_cleanup_timeout_while_its_worker_is_still_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(execution, "CANCELLATION_CLEANUP_TIMEOUT", 0.01)
    refs = published_manifests(monkeypatch)
    fixture = v3_fixture(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    calls: list[str] = []

    class StubbornWorker(FakeWorker):
        async def run(self, *, input_value: Any, arm_id: str) -> Any:
            calls.append(arm_id)
            if len(calls) == 1:
                entered.set()
                while not release.is_set():
                    try:
                        await release.wait()
                    except asyncio.CancelledError:
                        continue
            return await super().run(input_value=input_value, arm_id=arm_id)

    arguments = fixture.arguments
    arguments["workers"] = {arm.id: StubbornWorker() for arm in fixture.snapshot.arms}
    try:
        await cancel_when(asyncio.create_task(execute_plan(**arguments)), entered)
        manifest = RunManifest.model_validate_json(fixture.store.read_bytes(refs[-1]))
        assert manifest.interruption_ref is not None
        assert [f.code for f in verify_manifest(fixture.store, refs[-1])] == ["incomplete_run"]
        resumed = await execute_plan(**arguments, resume_from=refs[-1])
        assert isinstance(resumed, RunFailed)
        assert "interrupted run" in resumed.message
        assert len(calls) == 1
    finally:
        release.set()
        await asyncio.sleep(0.01)
    assert len(calls) == 1, "an abandoned dispatch loop started another cell"


async def test_resume_refuses_a_cancelled_run_whose_lost_time_cannot_be_restored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    refs = published_manifests(monkeypatch)
    fixture = v3_fixture(tmp_path)
    entered = asyncio.Event()
    calls: list[str] = []

    class BlockSecondWorker(FakeWorker):
        async def run(self, *, input_value: Any, arm_id: str) -> Any:
            calls.append(arm_id)
            if len(calls) == 2:
                entered.set()
                await asyncio.Event().wait()
            return await super().run(input_value=input_value, arm_id=arm_id)

    arguments = fixture.arguments
    arguments["workers"] = {arm.id: BlockSecondWorker() for arm in fixture.snapshot.arms}
    await cancel_when(asyncio.create_task(execute_plan(**arguments)), entered)
    manifest = RunManifest.model_validate_json(fixture.store.read_bytes(refs[-1]))
    assert len(manifest.execution_records) == 1  # The cancelled call saved no timestamps.
    resumed = await execute_plan(**arguments, resume_from=refs[-1])
    assert isinstance(resumed, RunFailed)
    assert "interrupted run" in resumed.message
    assert len(calls) == 2


async def test_resume_refuses_an_empty_v3_checkpoint(tmp_path: Path) -> None:
    fixture = v3_fixture(tmp_path)
    full = await execute_plan(**fixture.arguments)
    assert isinstance(full, RunSucceeded)
    plan = parse_execution_plan(json.loads(fixture.plan_bytes))
    missing = {cell.id for cell in plan.cells} | {item.id for item in plan.evaluations}
    empty = full.manifest.model_copy(update={
        "status": "incomplete", "missing_coordinates": tuple(sorted(missing)),
        "execution_records": {}, "evaluation_records": {}, "operating_records": {},
    })
    ref = str(fixture.store.publish_json(empty.model_dump(mode="json")))
    assert [f.code for f in verify_manifest(fixture.store, ref)] == ["incomplete_run"]
    calls: list[str] = []

    class RecordingWorker(FakeWorker):
        async def run(self, *, input_value: Any, arm_id: str) -> Any:
            calls.append(arm_id)
            return await super().run(input_value=input_value, arm_id=arm_id)

    arguments = fixture.arguments
    arguments["workers"] = {arm.id: RecordingWorker() for arm in fixture.snapshot.arms}
    resumed = await execute_plan(**arguments, resume_from=ref)
    assert isinstance(resumed, RunFailed)
    assert "cannot restore the authorized run limits" in resumed.message
    assert calls == []
