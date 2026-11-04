"""Verified checkpoints retain terminal outcomes and never dispatch them again."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from test_execution import FakeEvaluator, FakeWorker, default_runtime, execution_fixture

from assay.canonical import canonical_json
from assay.execution import AdmissionHalt, RunFailed, RunSucceeded, execute_plan
from assay.models import ExecutionOutcome, ExecutionPlanV3, parse_execution_plan
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
                raise AdmissionHalt("billing_uncertain", "pause before the next cell")
            return await super().run(**kwargs)

    arguments = fixture.arguments
    arguments["workers"] = {arm.id: CountWorker() for arm in fixture.snapshot.arms}
    first = await execute_plan(**arguments)
    assert isinstance(first, RunFailed) and first.manifest_ref is not None
    assert len(calls) == 1
    if limit == "wall":
        class ExpiredClock(datetime):
            @classmethod
            def now(cls, tz: Any = None) -> datetime:
                return datetime.now(tz) + timedelta(seconds=120)

        monkeypatch.setattr("assay.execution.datetime", ExpiredClock)
    resumed = await execute_plan(**arguments, resume_from=str(first.manifest_ref))
    assert isinstance(resumed, RunFailed)
    assert "ceiling" in resumed.message or "wall time" in resumed.message
    assert len(calls) == 1
    assert resumed.manifest is not None
    assert resumed.manifest.execution_records == first.manifest.execution_records
