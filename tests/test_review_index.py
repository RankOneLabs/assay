from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from review_fixture import ReviewFixture, materialize_review_fixture

from assay.review.index import CACHE_VERSION, IndexedOpaque, build_index, classify_object
from assay.review.model import ReadIssue
from assay.store import ObjectStore
from assay.verify import verify_bundle


@pytest.fixture
async def review_fixture(tmp_path: Path) -> ReviewFixture:
    return await materialize_review_fixture(tmp_path)


def test_fixture_objects_cover_review_discriminators(review_fixture: ReviewFixture) -> None:
    objects = [
        classify_object(
            "sha256:" + path.name,
            review_fixture.store.read_bytes("sha256:" + path.name),
        )
        for path in review_fixture.store.objects.iterdir()
    ]

    kinds = {item.kind for item in objects if not isinstance(item, ReadIssue)}
    assert {
        "manifest",
        "plan",
        "snapshot",
        "execution",
        "evaluation_failure",
        "evidence",
        "operating",
        "report_config",
        "report",
        "opaque",
    } <= kinds


def test_unknown_non_json_and_non_object_json_are_opaque() -> None:
    ref = "sha256:" + "0" * 64
    for raw in (b"not json", b"[]", b'{"schema_version":"future/9"}'):
        assert isinstance(classify_object(ref, raw), IndexedOpaque)


def test_discriminator_reads_are_type_guarded_and_classification_never_raises() -> None:
    ref = "sha256:" + "0" * 64
    hostile = [
        {"schema_version": []},
        {"record_schema": 4},
        {"record_schema": ["paa-evidence-record/0.3.0-draft"]},
        {"record_schema": "paa-evidence-record/0.3.0-draft", "payload": []},
        {"record_schema": "paa-operating-record/0.1.0-draft", "source_references": 1},
    ]
    results = [classify_object(ref, json.dumps(value).encode()) for value in hostile]
    assert all(isinstance(item, IndexedOpaque | ReadIssue) for item in results)


def test_malformed_recognized_wire_object_is_an_issue() -> None:
    ref = "sha256:" + "0" * 64
    result = classify_object(ref, b'{"schema_version":"assay-run-manifest/0.1.0"}')
    assert isinstance(result, ReadIssue)
    assert result.code == "malformed_object"


def test_fixture_index_groups_manifest_and_reports(review_fixture: ReviewFixture) -> None:
    index = build_index(review_fixture.store, refresh=True)

    manifested = [run for run in index.runs if run.manifest_ref == review_fixture.manifest_ref]
    assert len(manifested) == 1
    assert manifested[0].run_key == review_fixture.manifest_ref
    assert manifested[0].status == "complete"
    assert manifested[0].execution_records == {
        key: (ref,) for key, ref in sorted(review_fixture.result.manifest.execution_records.items())
    }
    assert {report.report_ref for report in index.reports} >= set(
        review_fixture.studies.report_refs.values()
    )


def test_unmanifested_records_group_by_run_and_full_plan_ref(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "store")
    plan_a = "sha256:" + "1" * 64
    plan_b = "sha256:" + "2" * 64

    def outcome(plan_ref: str, completed_at: str) -> dict[str, object]:
        input_ref = "sha256:" + "3" * 64
        return {
            "schema_version": "assay-execution-outcome/0.1.0",
            "run_id": "shared-run",
            "plan_ref": plan_ref,
            "started_at": "2026-01-01T00:00:00Z",
            "completed_at": completed_at,
            "coordinate": {
                "subject_id": "subject",
                "arm_id": "arm",
                "worker_repeat": 0,
                "realization_ref": input_ref,
            },
            "status": "failed",
            "input_ref": input_ref,
            "error_type": "FixtureFailure",
            "error_message": "expected",
        }

    first = str(store.publish_json(outcome(plan_a, "2026-01-01T00:00:01Z")))
    second = str(store.publish_json(outcome(plan_a, "2026-01-01T00:00:02Z")))
    store.publish_json(outcome(plan_b, "2026-01-01T00:00:01Z"))

    index = build_index(store, refresh=True)

    assert {run.run_key for run in index.runs} == {
        f"unmanifested:shared-run:{plan_a}",
        f"unmanifested:shared-run:{plan_b}",
    }
    conflicted = next(run for run in index.runs if run.plan_ref == plan_a)
    assert conflicted.execution_records["subject:arm:w0"] == tuple(sorted((first, second)))
    assert conflicted.conflicted_coordinates == ("subject:arm:w0",)
    assert conflicted.summary.cells_failed == 0
    assert conflicted.summary.cells_conflicted == 1
    assert conflicted.summary.cost.amounts == {}
    assert any(issue.code == "missing_accounting" for issue in index.issues)


def test_cache_is_disposable_and_stays_outside_object_namespace(
    review_fixture: ReviewFixture,
) -> None:
    before_entries = {path.name for path in review_fixture.store.objects.iterdir()}
    first = build_index(review_fixture.store, refresh=True)
    cache = review_fixture.store.root / "review-index.json"
    assert cache.is_file()
    cache.unlink()
    second = build_index(review_fixture.store)
    assert first == second

    cache.write_text("not json")
    assert build_index(review_fixture.store) == first
    cache.write_text(json.dumps({"version": CACHE_VERSION + 1, "key": {}, "objects": []}))
    assert build_index(review_fixture.store) == first
    assert {path.name for path in review_fixture.store.objects.iterdir()} == before_entries
    assert verify_bundle(review_fixture.bundle, review_fixture.manifest_ref) == ()


def test_bad_entries_report_issues_without_hiding_healthy_run(
    review_fixture: ReviewFixture, tmp_path: Path
) -> None:
    destination = tmp_path / "index-damaged"
    shutil.copytree(review_fixture.store.root, destination)
    store = ObjectStore(destination)
    (store.objects / "invalid-name").write_bytes(b"bad")
    opaque = next(
        item
        for item in build_index(store, refresh=True).objects
        if isinstance(item, IndexedOpaque)
    )
    (store.objects / opaque.ref.removeprefix("sha256:")).write_bytes(b"hash mismatch")

    index = build_index(store, refresh=True)

    assert any(run.manifest_ref == review_fixture.manifest_ref for run in index.runs)
    assert {issue.code for issue in index.issues} >= {
        "invalid_object_filename",
        "object_read",
    }


def test_empty_and_budget_limited_stores_return_results(tmp_path: Path) -> None:
    empty = build_index(ObjectStore(tmp_path / "missing"))
    assert empty.runs == ()
    assert empty.issues == ()

    store = ObjectStore(tmp_path / "limited")
    store.publish_json({"opaque": 1})
    partial = build_index(store, refresh=False, max_objects=0)
    assert partial.scan_incomplete
    assert any(issue.code == "scan_incomplete" for issue in partial.issues)
    complete = build_index(store, refresh=True, max_objects=0, max_bytes=0)
    assert not complete.scan_incomplete
    assert len(complete.objects) == 1


def test_non_writable_cache_is_diagnostic_but_does_not_hide_runs(
    review_fixture: ReviewFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def deny_replace(source: object, destination: object) -> None:
        del source, destination
        raise PermissionError("read-only root")

    monkeypatch.setattr(os, "replace", deny_replace)
    index = build_index(review_fixture.store, refresh=True)

    assert any(run.manifest_ref == review_fixture.manifest_ref for run in index.runs)
    assert any(issue.code == "cache_write" for issue in index.issues)


def test_manifest_reachable_model_output_cannot_create_loose_run(
    review_fixture: ReviewFixture,
) -> None:
    manifest = review_fixture.result.manifest.model_dump(mode="json")
    coordinate, old_ref = next(iter(manifest["execution_records"].items()))
    outcome = json.loads(review_fixture.store.read_bytes(old_ref))
    spoof = {
        "record_schema": "paa-evidence-record/0.3.0-draft",
        "payload": {
            "run_id": "model-chosen-run",
            "plan_ref": manifest["plan_ref"],
            "cell_id": "invented:cell:w0",
            "evaluator_id": "invented",
            "evaluator_repeat": 0,
        },
    }
    spoof_ref = str(review_fixture.store.publish_json(spoof))
    outcome.update(
        {
            "status": "succeeded",
            "output_ref": spoof_ref,
            "error_type": None,
            "error_message": None,
        }
    )
    manifest["execution_records"][coordinate] = str(review_fixture.store.publish_json(outcome))
    review_fixture.store.publish_json(manifest)

    index = build_index(review_fixture.store, refresh=True)

    assert all(run.run_id != "model-chosen-run" for run in index.runs)


def test_orphan_and_duplicate_accounting_are_diagnostic_and_not_summed(
    tmp_path: Path,
) -> None:
    store = ObjectStore(tmp_path / "accounting")
    plan_ref = "sha256:" + "1" * 64
    input_ref = "sha256:" + "2" * 64
    outcome = {
        "schema_version": "assay-execution-outcome/0.1.0",
        "run_id": "accounting-run",
        "plan_ref": plan_ref,
        "started_at": "2026-01-01T00:00:00Z",
        "completed_at": "2026-01-01T00:00:01Z",
        "coordinate": {
            "subject_id": "subject",
            "arm_id": "arm",
            "worker_repeat": 0,
            "realization_ref": input_ref,
        },
        "status": "failed",
        "input_ref": input_ref,
        "error_type": "FixtureFailure",
        "error_message": "expected",
    }
    outcome_ref = str(store.publish_json(outcome))
    provenance_ref = str(
        store.publish_json(
            {
                "run_id": "accounting-run",
                "attempt": "worker:subject:arm:w0",
            }
        )
    )
    for suffix in ("one", "two"):
        store.publish_json(
            {
                "record_schema": "paa-operating-record/0.1.0-draft",
                "record_id": suffix,
                "source_references": [outcome_ref, provenance_ref],
                "price": {"amount": 9, "currency": "USD"},
            }
        )
    store.publish_json(
        {
            "record_schema": "paa-operating-record/0.1.0-draft",
            "record_id": "orphan",
            "source_references": [provenance_ref],
            "price": {"amount": 99, "currency": "USD"},
        }
    )

    index = build_index(store, refresh=True)

    assert len(index.runs) == 1
    assert index.runs[0].summary.cost.amounts == {}
    assert index.runs[0].operating_records == ()
    assert {issue.code for issue in index.issues} >= {
        "duplicate_accounting",
        "orphan_accounting",
    }
