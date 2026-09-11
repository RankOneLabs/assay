from __future__ import annotations

import json
import os
import tempfile
import weakref
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from test_execution import FakeEvaluator, FakeWorker, execution_fixture
from test_reports import report_config

from assay.canonical import canonical_json, digest_bytes
from assay.execution import EvaluationSuccess, RunFailed, RunSucceeded, WorkerSuccess, execute_plan
from assay.models import StatisticalProfile, StudySnapshot
from assay.planning import compile_plan
from assay.report_engine import persist_report
from assay.reporting import _IndexStream, bootstrap_paired, paired_effect
from assay.schema_export import check_schemas, schema_documents
from assay.schema_validation import schema_validators
from assay.store import ObjectIntegrityError, ObjectStore, _VerificationSession
from assay.verify import export_bundle, reference_closure, verify_bundle, verify_manifest


async def test_retained_worker_output_cannot_change_scored_bytes(tmp_path: Path) -> None:
    fixture = execution_fixture(
        ObjectStore(tmp_path), subject_ids=("ok",), worker_repeats=1, concurrency=1
    )

    class RetainingWorker(FakeWorker):
        retained: dict[str, int] | None = None

        async def run(self, **kwargs: Any) -> WorkerSuccess:
            if self.retained is not None:
                self.retained["score"] = 1
            self.retained = {"score": 0}
            return WorkerSuccess(self.retained)

    class MutatingEvaluator(FakeEvaluator):
        async def evaluate(self, **kwargs: Any) -> EvaluationSuccess:
            output = kwargs["output"]
            verdict = float(output["score"])
            output["score"] = 1
            return EvaluationSuccess(verdict)

    worker = RetainingWorker()
    args = fixture.arguments | {
        "workers": {arm.id: worker for arm in fixture.snapshot.arms},
        "evaluators": {"quality": MutatingEvaluator()},
    }
    result = await execute_plan(**args)
    assert isinstance(result, RunSucceeded), result
    for ref in result.manifest.evaluation_records.values():
        record = json.loads(fixture.store.read_bytes(ref))
        output = json.loads(fixture.store.read_bytes(record["boundary"]["output_ref"]))
        assert record["verdict"]["value"] == output["score"] == 0
    assert verify_manifest(fixture.store, str(result.manifest_ref)) == ()


@pytest.mark.parametrize("schema_reference", ["identity", "digest", "remote", "duplicate"])
async def test_runtime_and_offline_share_schema_policy(
    tmp_path: Path, schema_reference: str
) -> None:
    fixture = execution_fixture(
        ObjectStore(tmp_path), subject_ids=("ok",), worker_repeats=1, evaluator_repeats=1
    )
    store = fixture.store
    snapshot = fixture.snapshot.model_dump(mode="json")
    declaration = snapshot["evaluators"][0]
    schema = json.loads(store.read_bytes(declaration["payload_schema_ref"]))
    if schema_reference == "digest":
        schema["allOf"][0]["$ref"] = snapshot["evidence_schema_ref"]
    elif schema_reference == "remote":
        schema["allOf"][0]["$ref"] = "https://unavailable.invalid/schema.json"
    elif schema_reference == "duplicate":
        schema["$id"] = "https://paa.dev/paa-evidence-record.schema.json"
        declaration["payload_schema"] = schema["$id"]
    declaration["payload_schema_ref"] = str(store.publish_json(schema))
    snapshot = StudySnapshot.model_validate(snapshot)
    plan = compile_plan(
        snapshot,
        snapshot_ref=str(store.publish_json(snapshot.model_dump(mode="json"))),
        worker_repeats=1,
        jig_revision="test",
    )
    data = canonical_json(plan.model_dump(mode="json"))
    result = await execute_plan(**(fixture.arguments | {
        "snapshot": snapshot, "plan_bytes": data, "authorization": digest_bytes(data),
    }))
    if schema_reference == "duplicate":
        assert isinstance(result, RunFailed)
        assert "same identity" in result.message
        with pytest.raises(ValueError, match="same identity"):
            schema_validators(store, snapshot)
        return
    assert isinstance(result, RunSucceeded), result
    validators = schema_validators(store, snapshot)
    for ref in result.manifest.evaluation_records.values():
        record = json.loads(store.read_bytes(ref))
        if schema_reference == "remote":
            assert record["error_type"] == "InvalidVerdict"
            with pytest.raises(Exception, match="Unresolvable"):
                validators[declaration["payload_schema_ref"]].validate({})
        else:
            assert "verdict" in record
            validators[declaration["payload_schema_ref"]].validate(record)
    assert verify_manifest(store, str(result.manifest_ref)) == ()


async def test_payload_lifetime_is_bounded_by_active_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = execution_fixture(
        ObjectStore(tmp_path), subject_ids=tuple(f"s{i}" for i in range(10)),
        worker_repeats=2, concurrency=1,
    )
    live: weakref.WeakValueDictionary[int, Any] = weakref.WeakValueDictionary()

    class Payload(dict[str, Any]):
        pass

    def tracked(value: dict[str, Any]) -> Payload:
        payload = Payload(value)
        live[id(payload)] = payload
        return payload

    original_loads = json.loads

    def loads(*args: Any, **kwargs: Any) -> Any:
        value = original_loads(*args, **kwargs)
        if isinstance(value, dict) and set(value) == {"subject", "arm"}:
            return tracked(value)
        return value

    class Worker(FakeWorker):
        async def run(self, **kwargs: Any) -> WorkerSuccess:
            assert len(live) == 1, "executor retained inactive inputs or prior outputs"
            return WorkerSuccess(tracked({"score": 0}))

    monkeypatch.setattr(json, "loads", loads)
    result = await execute_plan(**(fixture.arguments | {
        "workers": {arm.id: Worker() for arm in fixture.snapshot.arms},
    }))
    assert isinstance(result, RunSucceeded), result
    for ref in result.manifest.execution_records.values():
        assert json.loads(fixture.store.read_bytes(ref))["status"] == "succeeded"
    assert not live


async def test_staging_residue_is_not_a_committed_bundle_object(tmp_path: Path) -> None:
    fixture = execution_fixture(ObjectStore(tmp_path / "source"), subject_ids=("ok",))
    result = await execute_plan(**fixture.arguments)
    assert isinstance(result, RunSucceeded)
    bundle = export_bundle(fixture.store, str(result.manifest_ref), tmp_path / "bundle")
    fd, temporary = tempfile.mkstemp(prefix=".publish-", dir=bundle.root / "staging")
    os.close(fd)
    assert verify_bundle(bundle, str(result.manifest_ref)) == ()
    # Do not weaken the strict committed namespace to ignore arbitrary filenames.
    Path(temporary).rename(bundle.objects / Path(temporary).name)
    failures = verify_bundle(bundle, str(result.manifest_ref))
    assert any(f.code == "bundle_integrity" for f in failures)


def test_publication_uses_separate_staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = ObjectStore(tmp_path)
    original_link = os.link
    seen = []

    def link(source: Path, target: Path) -> None:
        seen.append(source)
        assert source.parent == store.root / "staging"
        assert target.parent == store.objects
        original_link(source, target)

    monkeypatch.setattr(os, "link", link)
    store.publish_json({"value": 1})
    assert len(seen) == 1 and not seen[0].exists()


async def test_export_reuses_verified_bytes_but_next_operation_rechecks(tmp_path: Path) -> None:
    class CountingStore(ObjectStore):
        reads: Counter[str]

        def read_bytes(self, ref: Any) -> bytes:
            self.reads[str(ref)] += 1
            return super().read_bytes(ref)

    store = CountingStore(tmp_path / "source")
    store.reads = Counter()
    fixture = execution_fixture(store, subject_ids=("ok",))
    result = await execute_plan(**fixture.arguments)
    assert isinstance(result, RunSucceeded)
    report_ref = persist_report(store, report_config(result))
    expected = reference_closure(store, (str(report_ref),))
    store.reads.clear()
    bundle = export_bundle(store, str(report_ref), tmp_path / "bundle")
    assert set(store.reads) == expected
    assert set(store.reads.values()) == {1}
    assert verify_bundle(bundle, str(report_ref)) == ()
    store._path(report_ref).write_bytes(b"tampered")
    with pytest.raises(ObjectIntegrityError):
        export_bundle(store, str(report_ref), tmp_path / "other")


def test_verification_payload_cache_is_bounded_and_eviction_rechecks(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    first = store.publish_bytes(b"1234")
    second = store.publish_bytes(b"5678")
    session = _VerificationSession(store, byte_limit=4)
    assert session.read_bytes(first) == b"1234"
    assert session.read_bytes(second) == b"5678"
    assert session.cached_bytes == 4 and len(session.cache) == 1
    store._path(first).write_bytes(b"bad")
    with pytest.raises(ObjectIntegrityError):
        session.read_bytes(first)


def test_schema_check_rejects_empty_missing_extra_and_drift(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="inventory"):
        check_schemas(tmp_path)
    for name, data in schema_documents().items():
        (tmp_path / name).write_bytes(data)
    check_schemas(tmp_path)
    extra = tmp_path / "extra.schema.json"
    extra.write_text("{}")
    with pytest.raises(ValueError, match="inventory"):
        check_schemas(tmp_path)
    extra.unlink()
    path = tmp_path / next(iter(schema_documents()))
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="differs"):
        check_schemas(tmp_path)
    path.unlink()
    with pytest.raises(ValueError, match="inventory"):
        check_schemas(tmp_path)


def test_legacy_statistical_profile_is_not_silently_reinterpreted() -> None:
    with pytest.raises(ValidationError):
        StatisticalProfile(name="paired-v1", seed=1, bootstrap_samples=100)  # type: ignore[arg-type]


def test_exact_mean_handles_cancellation_and_large_finite_values() -> None:
    assert paired_effect([1e16, 1, -1e16]) == 1 / 3
    assert paired_effect([1e308, 1e308]) == 1e308
    assert bootstrap_paired([1e308, 1e308], seed=1, samples=100) == ((1e308, 1e308), 1 / 101)


def test_sampler_rejection_and_domain_separation() -> None:
    stream = _IndexStream(7, b"observed")
    stream.words = [4, 2**64 - 1]
    assert stream.index(3) == 1  # Discard the out-of-range uint64 before modulo.
    left, right = _IndexStream(7, b"observed"), _IndexStream(7, b"null")
    assert [left.index(100) for _ in range(10)] != [right.index(100) for _ in range(10)]


def test_paired_v2_exact_golden_vectors() -> None:
    stream = _IndexStream(7, b"observed")
    assert [stream.index(17) for _ in range(16)] == [
        4, 15, 15, 10, 14, 2, 5, 4, 4, 2, 13, 11, 6, 5, 4, 16,
    ]
    stream = _IndexStream(7, b"null")
    assert [stream.index(17) for _ in range(16)] == [
        10, 10, 4, 3, 14, 7, 15, 5, 11, 6, 4, 2, 9, 1, 2, 2,
    ]
    interval, p = bootstrap_paired([-1.25, 0.1, 2.75, 8.0], seed=7, samples=1000)
    assert tuple(value.hex() for value in (*interval, p)) == (
        "-0x1.2666666666666p-1", "0x1.819999999999ap+2", "0x1.2286857f9dcb5p-3",
    )
