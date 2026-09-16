from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

import pytest
from test_execution import FakeWorker, execution_fixture

import assay.execution as execution_module
from assay.execution import (
    AdmissionHalt,
    RunFailed,
    WorkerFailure,
    WorkerSuccess,
    execute_plan,
)
from assay.store import ObjectStore
from assay.verify import verify_manifest


async def test_cancellation_persists_incomplete_manifest_before_reraising(tmp_path: Any) -> None:
    fixture = execution_fixture(ObjectStore(tmp_path), subject_ids=("ok",), concurrency=2)
    arguments = fixture.arguments
    started = asyncio.Event()

    class BlockingWorker(FakeWorker):
        async def run(self, **kwargs: Any) -> WorkerSuccess:
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    arguments["workers"] = {arm.id: BlockingWorker() for arm in fixture.snapshot.arms}
    running = asyncio.create_task(execute_plan(**arguments))
    await started.wait()
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running

    # No manifest is returned by execute_plan on cancellation, but one must
    # have been durably published to the store before cancellation reached us.
    manifests = []
    for path in fixture.store.objects.iterdir():
        try:
            value = json.loads(path.read_bytes())
        except (OSError, ValueError):
            continue
        if isinstance(value, dict) and value.get("schema_version") == "assay-run-manifest/0.1.0":
            manifests.append(value)
    assert len(manifests) == 1
    manifest = manifests[0]
    assert manifest["status"] == "incomplete"
    assert manifest["missing_coordinates"]


async def test_cleanup_timeout_persists_a_typed_interruption_record(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(execution_module, "CANCELLATION_CLEANUP_TIMEOUT", 0.05)
    fixture = execution_fixture(ObjectStore(tmp_path), subject_ids=("ok",), concurrency=2)
    arguments = fixture.arguments
    started = asyncio.Event()

    class StuckCleanupWorker(FakeWorker):
        async def run(self, **kwargs: Any) -> WorkerSuccess:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                # Cleanup that outlives the bounded shield's window. Shielded
                # so the drain's own re-cancel doesn't cut the sleep short;
                # it still finishes soon after so it doesn't leak into later
                # tests.
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.shield(asyncio.sleep(0.3))
                raise
            raise AssertionError("unreachable")

    arguments["workers"] = {arm.id: StuckCleanupWorker() for arm in fixture.snapshot.arms}
    running = asyncio.create_task(execute_plan(**arguments))
    await started.wait()
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running

    manifests = []
    for path in fixture.store.objects.iterdir():
        try:
            value = json.loads(path.read_bytes())
        except (OSError, ValueError):
            continue
        if isinstance(value, dict) and value.get("schema_version") == "assay-run-manifest/0.1.0":
            manifests.append(value)
    assert len(manifests) == 1
    manifest = manifests[0]
    assert manifest["status"] == "incomplete"
    assert manifest["interruption_ref"] is not None
    interruption = json.loads(fixture.store.read_bytes(manifest["interruption_ref"]))
    assert interruption["schema_version"] == "assay-cleanup-interruption/0.1.0"
    assert interruption["run_id"] == manifest["run_id"]
    assert interruption["reason"] == "cleanup_timeout"
    assert interruption["outstanding_tasks"] >= 1
    manifest_ref = next(
        f"sha256:{path.name}"
        for path in fixture.store.objects.iterdir()
        if json.loads(path.read_bytes()) == manifest
    )
    assert {failure.code for failure in verify_manifest(fixture.store, manifest_ref)} <= {
        "incomplete_run"
    }


async def test_no_later_cell_starts_after_typed_admission_halt(tmp_path: Any) -> None:
    fixture = execution_fixture(
        ObjectStore(tmp_path), subject_ids=("ok", "fails"), worker_repeats=1, concurrency=1
    )
    arguments = fixture.arguments
    calls: list[str] = []

    class HaltingWorker(FakeWorker):
        async def run(self, *, input_value: Any, arm_id: str) -> WorkerSuccess | WorkerFailure:
            calls.append(input_value["subject"])
            if len(calls) == 1:
                raise AdmissionHalt("budget_exhausted", "budget exhausted mid-run")
            return await super().run(input_value=input_value, arm_id=arm_id)

    arguments["workers"] = {arm.id: HaltingWorker() for arm in fixture.snapshot.arms}
    result = await execute_plan(**arguments)
    assert isinstance(result, RunFailed)
    assert result.error_type == "AdmissionHalt"
    assert len(calls) == 1
    assert result.manifest is not None and result.manifest.status == "incomplete"
    assert len(result.manifest.execution_records) == 1
    outcome = json.loads(
        fixture.store.read_bytes(next(iter(result.manifest.execution_records.values())))
    )
    assert outcome["status"] == "failed"
    assert outcome["error_type"] == "budget_exhausted"
    assert result.manifest_ref is not None
    assert verify_manifest(fixture.store, str(result.manifest_ref)) != ()
