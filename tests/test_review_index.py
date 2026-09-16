from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from review_fixture import ReviewFixture, materialize_review_fixture
from test_execution import execution_fixture

from assay.models import RuntimeProfile
from assay.planning import compile_plan_v2
from assay.review import index as review_index
from assay.review.index import (
    CACHE_VERSION,
    IndexedOpaque,
    IndexedPlan,
    build_index,
    classify_object,
)
from assay.review.model import ReadIssue
from assay.store import ObjectRef, ObjectStore
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


@pytest.mark.parametrize("damage", ["value", "omission", "duplicate", "source"])
def test_warm_cache_cannot_hide_changed_values_or_objects(
    review_fixture: ReviewFixture, damage: str
) -> None:
    store = review_fixture.store
    cold = build_index(store)
    cache_path = store.root / "review-index.json"
    cache = json.loads(cache_path.read_bytes())
    entry = next(item for item in cache["objects"] if item["ref"] == review_fixture.manifest_ref)
    if damage == "value":
        entry["value"]["run_id"] = "forged-cache-run"
    elif damage == "omission":
        cache["objects"].remove(entry)
    elif damage == "duplicate":
        cache["objects"].append(entry)
    else:
        path = store.objects / review_fixture.manifest_ref.removeprefix("sha256:")
        stat = path.stat()
        path.write_bytes(b"corrupt manifest")
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    cache_path.write_text(json.dumps(cache))

    warm = build_index(store)
    if damage == "source":
        assert any(
            issue.code == "object_read" and issue.ref == review_fixture.manifest_ref
            for issue in warm.issues
        )
        assert all(run.manifest_ref != review_fixture.manifest_ref for run in warm.runs)
    else:
        assert warm == cold


def test_extra_coordinates_do_not_reduce_missingness(review_fixture: ReviewFixture) -> None:
    store = review_fixture.store
    manifest = review_fixture.result.manifest.model_dump(mode="json")
    plan = json.loads(store.read_bytes(manifest["plan_ref"]))
    execution_ref = next(iter(manifest["execution_records"].values()))
    evaluation_ref = next(iter(manifest["evaluation_records"].values()))
    manifest["execution_records"] = {"extra:arm:w0": execution_ref}
    manifest["evaluation_records"] = {"extra:arm:w0:judge:e0": evaluation_ref}
    ref = str(store.publish_json(manifest))
    run = next(run for run in build_index(store).runs if run.manifest_ref == ref)
    assert run.summary.cells_missing == len(plan["cells"])
    assert run.summary.evaluations_missing == len(plan["evaluations"])


@pytest.mark.parametrize("coverage", ["measured", "estimated", "mixed"])
def test_cost_uses_provenance_coverage(review_fixture: ReviewFixture, coverage: str) -> None:
    store = review_fixture.store
    manifest = review_fixture.result.manifest.model_dump(mode="json")
    attempt, ref = next(iter(manifest["operating_records"].items()))
    record = json.loads(store.read_bytes(ref))
    for position, source in enumerate(record["source_references"]):
        detail = json.loads(store.read_bytes(source))
        if isinstance(detail, dict) and "coverage" in detail and "attempt" in detail:
            detail["coverage"] = coverage
            record["source_references"][position] = str(store.publish_json(detail))
            break
    else:
        pytest.fail("fixture has no accounting provenance")
    record["price"] = {"amount": 2, "currency": "USD", "basis": "fixture"}
    manifest["operating_records"] = {attempt: str(store.publish_json(record))}
    ref = str(store.publish_json(manifest))
    run = next(run for run in build_index(store).runs if run.manifest_ref == ref)
    assert run.summary.cost.coverage == coverage
    assert run.summary.cost.coverage_counts == {coverage: 1}
    assert run.summary.cost.amounts == {"USD": 2.0}


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


def test_deeply_nested_json_cannot_escape_classifier() -> None:
    raw = b"[" * (sys.getrecursionlimit() * 2) + b"0" + b"]" * (sys.getrecursionlimit() * 2)
    assert isinstance(classify_object("sha256:" + "0" * 64, raw), ReadIssue | IndexedOpaque)


def test_index_imports_without_dev_or_server_dependencies() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            'import sys; sys.modules["paa_contracts"] = None; '
            'sys.modules["fastapi"] = None; import assay.review.index',
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_schema_invalid_loose_evidence_is_not_a_success(review_fixture: ReviewFixture) -> None:
    store = review_fixture.store
    evidence = next(
        json.loads(store.read_bytes(ref))
        for ref in review_fixture.result.manifest.evaluation_records.values()
        if json.loads(store.read_bytes(ref)).get("record_schema")
    )
    evidence["payload"]["run_id"] = "loose-invalid"
    evidence["record_id"] = 123
    ref = str(store.publish_json(evidence))
    run = next(run for run in build_index(store).runs if run.run_id == "loose-invalid")
    assert run.candidate_only
    assert run.summary.evaluations_succeeded == 0
    assert run.summary.evaluations_invalid == 1
    assert any(
        issue.code == "record_schema_validation" and issue.ref == ref for issue in run.issues
    )
    assert any(issue.code == "candidate_only" for issue in run.issues)


def test_corrupt_pinned_schema_does_not_hide_manifest(review_fixture: ReviewFixture) -> None:
    store = review_fixture.store
    ref = review_fixture.snapshot.evidence_schema_ref
    (store.objects / ref.removeprefix("sha256:")).write_bytes(b"corrupt schema")
    index = build_index(store)
    run = next(run for run in index.runs if run.manifest_ref == review_fixture.manifest_ref)
    assert run.summary.evaluations_succeeded == 0
    assert run.summary.cost.amounts == {}
    assert any(issue.code == "object_read" and issue.ref == ref for issue in index.issues)


def test_explicit_edges_through_opaque_output_suppress_spoofed_loose_run(
    review_fixture: ReviewFixture,
) -> None:
    store = review_fixture.store
    manifest = review_fixture.result.manifest.model_dump(mode="json")
    coordinate, terminal_ref = next(iter(manifest["execution_records"].items()))
    terminal = json.loads(store.read_bytes(terminal_ref))
    spoof = dict(terminal, run_id="nested-model-spoof")
    spoof_ref = str(store.publish_json(spoof))
    opaque_ref = str(store.publish_json({"assay_object_refs": [spoof_ref]}))
    terminal.update(status="succeeded", output_ref=opaque_ref, error_type=None, error_message=None)
    manifest["execution_records"][coordinate] = str(store.publish_json(terminal))
    store.publish_json(manifest)
    index = build_index(store)
    assert all(run.run_id != "nested-model-spoof" for run in index.runs)


def test_stale_report_cannot_claim_recomputable(review_fixture: ReviewFixture) -> None:
    report = next(
        report
        for report in build_index(review_fixture.store).reports
        if report.report_ref == review_fixture.studies.stale_report_ref
    )
    assert not report.recomputable
    assert report.recompute_disabled_reason == "unsupported report engine version"


def test_indexing_bundle_preserves_verification(review_fixture: ReviewFixture) -> None:
    store = review_fixture.bundle
    before = set(store.objects.iterdir())
    build_index(store)
    build_index(store, refresh=True)
    assert set(store.objects.iterdir()) == before
    assert [f.code for f in verify_bundle(store, review_fixture.manifest_ref)] == ["incomplete_run"]


def test_loose_accounting_requires_unique_schema_valid_attribution(
    review_fixture: ReviewFixture,
    tmp_path: Path,
) -> None:
    store = ObjectStore(tmp_path / "loose-accounting")
    shutil.copytree(review_fixture.bundle.root, store.root)
    (store.objects / review_fixture.manifest_ref.removeprefix("sha256:")).unlink()
    manifest = review_fixture.result.manifest
    attempt, original_ref = next(iter(manifest.operating_records.items()))
    record = json.loads(store.read_bytes(original_ref))
    for position, source in enumerate(record["source_references"]):
        detail = json.loads(store.read_bytes(source))
        if isinstance(detail, dict) and "coverage" in detail and "attempt" in detail:
            detail["coverage"] = "estimated"
            record["source_references"][position] = str(store.publish_json(detail))
            break
    record["price"] = {"amount": 2, "currency": "USD", "basis": "fixture"}
    (store.objects / original_ref.removeprefix("sha256:")).unlink()
    measured_ref = str(store.publish_json(record))

    before = build_index(store)
    assert len(before.runs) == 1
    run = before.runs[0]
    assert not run.candidate_only
    assert measured_ref in run.operating_records
    assert run.summary.cost.amounts == {"USD": 2.0}
    assert run.summary.cost.unaccounted_attempts == 0

    duplicate = dict(record, record_id="duplicate-attempt")
    duplicate_ref = str(store.publish_json(duplicate))
    run = build_index(store).runs[0]
    assert run.summary.cost.amounts == {}
    assert measured_ref not in run.operating_records
    assert duplicate_ref not in run.operating_records
    assert run.summary.cost.unaccounted_attempts == 1

    (store.objects / duplicate_ref.removeprefix("sha256:")).unlink()
    (store.objects / measured_ref.removeprefix("sha256:")).unlink()
    record["price"]["amount"] = -1
    invalid_ref = str(store.publish_json(record))
    run = build_index(store).runs[0]
    assert run.candidate_only
    assert invalid_ref not in run.operating_records
    assert run.summary.cost.amounts == {}
    assert any(
        issue.ref == invalid_ref and issue.code == "record_schema_validation"
        for issue in run.issues
    )


def test_uncertain_accounting_is_accepted_and_never_reads_as_measured_zero(
    review_fixture: ReviewFixture,
    tmp_path: Path,
) -> None:
    """An attempt that failed before usage/price was ever observed must index

    as "uncertain" coverage with no amount -- not as an invalid_accounting
    issue, and never as a silently-summed zero cost.
    """
    store = ObjectStore(tmp_path / "uncertain-index")
    shutil.copytree(review_fixture.bundle.root, store.root)
    manifest_dict = review_fixture.result.manifest.model_dump(mode="json")
    attempt, original_ref = next(iter(manifest_dict["operating_records"].items()))
    record = json.loads(store.read_bytes(original_ref))
    for position, source in enumerate(record["source_references"]):
        detail = json.loads(store.read_bytes(source))
        if isinstance(detail, dict) and "coverage" in detail and "attempt" in detail:
            detail["coverage"] = "uncertain"
            record["source_references"][position] = str(store.publish_json(detail))
            break
    record["price"] = None
    (store.objects / original_ref.removeprefix("sha256:")).unlink()
    uncertain_ref = str(store.publish_json(record))
    manifest_dict["operating_records"][attempt] = uncertain_ref
    manifest_ref = str(store.publish_json(manifest_dict))

    index = build_index(store, refresh=True)
    run = next(r for r in index.runs if r.manifest_ref == manifest_ref)
    assert uncertain_ref in run.operating_records
    assert not any(issue.ref == uncertain_ref for issue in run.summary.cost.issues)
    assert run.summary.cost.coverage_counts.get("uncertain") == 1
    assert 0.0 not in run.summary.cost.amounts.values()


def test_loose_cost_cannot_use_manifested_terminal_as_second_source(
    review_fixture: ReviewFixture,
) -> None:
    store = review_fixture.store
    manifest = review_fixture.result.manifest
    coordinate, original_ref = next(iter(manifest.execution_records.items()))
    outcome = json.loads(store.read_bytes(original_ref))
    outcome["run_id"] = "loose-cost"
    loose_ref = str(store.publish_json(outcome))
    operating = json.loads(store.read_bytes(manifest.operating_records[f"worker:{coordinate}"]))
    for position, source in enumerate(operating["source_references"]):
        detail = json.loads(store.read_bytes(source))
        if isinstance(detail, dict) and "coverage" in detail and "attempt" in detail:
            detail.update(run_id="loose-cost", coverage="estimated")
            operating["source_references"][position] = str(store.publish_json(detail))
    operating["source_references"].append(loose_ref)
    operating["price"] = {"amount": 100, "currency": "USD", "basis": "fixture"}
    ref = str(store.publish_json(operating))
    index = build_index(store)
    run = next(run for run in index.runs if run.run_id == "loose-cost")
    assert run.operating_records == ()
    assert run.summary.cost.amounts == {}
    assert any(issue.ref == ref and issue.code == "orphan_accounting" for issue in index.issues)


def test_total_read_budget_covers_grouping_and_schema_reads(review_fixture: ReviewFixture) -> None:
    class CountedStore(ObjectStore):
        def __init__(self, root: Path) -> None:
            super().__init__(root)
            self.total = 0
            self.reads: list[str] = []

        def read_bytes(self, ref: str | ObjectRef) -> bytes:
            self.total += (self.objects / str(ref).removeprefix("sha256:")).stat().st_size
            self.reads.append(str(ref))
            return super().read_bytes(ref)

    store = CountedStore(review_fixture.store.root)
    total_size = sum(path.stat().st_size for path in store.objects.iterdir())
    complete = build_index(store, max_bytes=total_size)
    assert not complete.scan_incomplete
    assert store.total == total_size
    assert len(store.reads) == len(set(store.reads))
    store.total = 0
    store.reads.clear()
    partial = build_index(store, max_bytes=total_size // 2)
    assert partial.scan_incomplete
    assert store.total <= total_size // 2
    assert any(issue.code == "scan_incomplete" for issue in partial.issues)


def test_fixture_index_groups_manifest_and_reports(review_fixture: ReviewFixture) -> None:
    index = build_index(review_fixture.store, refresh=True)

    manifested = [run for run in index.runs if run.manifest_ref == review_fixture.manifest_ref]
    assert len(manifested) == 1
    assert manifested[0].run_key == review_fixture.manifest_ref
    # The fixture's one injected execution failure leaves its own evaluation
    # genuinely unavailable, so the manifest is honestly incomplete.
    assert manifested[0].status == "incomplete"
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


def test_v2_plan_discovers_with_generic_runtime_identity_and_no_jig_revision(
    tmp_path: Path,
) -> None:
    store = ObjectStore(tmp_path / "store")
    study = execution_fixture(store, subject_ids=("ok",), worker_repeats=1).snapshot
    snapshot_ref = str(store.publish_json(study.model_dump(mode="json")))
    for declaration in (*study.arms, *study.evaluators):
        store.publish_json(declaration.model_dump(mode="json"))
    store.publish_json([arm.conditions for arm in sorted(study.arms, key=lambda item: item.id)])
    runtime = RuntimeProfile(
        id="pier", version="1.0.0", configuration_ref=str(store.publish_json({"pier": True}))
    )
    plan = compile_plan_v2(
        study, snapshot_ref=snapshot_ref, worker_repeats=1, runtime=runtime
    )
    plan_ref = str(store.publish_json(plan.model_dump(mode="json")))

    plan_item = classify_object(plan_ref, store.read_bytes(plan_ref))
    assert isinstance(plan_item, IndexedPlan)
    assert plan_item.value == plan

    input_ref = "sha256:" + "3" * 64
    outcome = {
        "schema_version": "assay-execution-outcome/0.1.0",
        "run_id": "pier-run",
        "plan_ref": plan_ref,
        "started_at": "2026-01-01T00:00:00Z",
        "completed_at": "2026-01-01T00:00:01Z",
        "coordinate": {
            "subject_id": "ok",
            "arm_id": "reference",
            "worker_repeat": 0,
            "realization_ref": input_ref,
        },
        "status": "failed",
        "input_ref": input_ref,
        "error_type": "FixtureFailure",
        "error_message": "expected",
    }
    store.publish_json(outcome)

    index = build_index(store, refresh=True)
    run = next(run for run in index.runs if run.plan_ref == plan_ref)
    assert run.summary.runtime_id == "pier"
    assert run.summary.runtime_version == "1.0.0"
    assert run.summary.jig_revision is None


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
    assert [f.code for f in verify_bundle(review_fixture.bundle, review_fixture.manifest_ref)] == [
        "incomplete_run"
    ]


def test_warm_cache_hit_preserves_discovered_values(
    review_fixture: ReviewFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = review_fixture.store.root / "review-index.json"
    assert not cache.exists()
    cold = build_index(review_fixture.store)
    assert cache.is_file()

    def unexpected_scan(*args: object, **kwargs: object) -> None:
        pytest.fail("warm cache hit must not rescan")

    monkeypatch.setattr(review_index, "_scan", unexpected_scan)
    assert build_index(review_fixture.store) == cold


def test_loose_record_with_manifest_identity_preserves_manifest_membership(
    review_fixture: ReviewFixture,
) -> None:
    store = review_fixture.store
    manifest = review_fixture.result.manifest
    before = build_index(store)
    manifested_before = next(
        run for run in before.runs if run.manifest_ref == review_fixture.manifest_ref
    )
    coordinate, record_ref = next(iter(manifest.execution_records.items()))
    record = json.loads(store.read_bytes(record_ref))
    record.update(
        status="failed",
        output_ref=None,
        error_type="LooseFailure",
        error_message="unclaimed terminal at the same coordinate",
    )
    loose_ref = str(store.publish_json(record))
    assert loose_ref not in manifest.execution_records.values()

    after = build_index(store)
    manifested_after = next(
        run for run in after.runs if run.manifest_ref == review_fixture.manifest_ref
    )
    assert manifested_after.execution_records == manifested_before.execution_records
    same_identity = [
        run
        for run in after.runs
        if run.run_id == manifest.run_id and run.plan_ref == manifest.plan_ref
    ]
    assert len(same_identity) == 2
    loose = next(run for run in same_identity if run.manifest_ref is None)
    assert loose.status == "unmanifested"
    assert loose.run_key == f"unmanifested:{manifest.run_id}:{manifest.plan_ref}"
    assert loose.execution_records == {coordinate: (loose_ref,)}


def test_bad_entries_report_issues_without_hiding_healthy_run(
    review_fixture: ReviewFixture, tmp_path: Path
) -> None:
    destination = tmp_path / "index-damaged"
    shutil.copytree(review_fixture.store.root, destination)
    store = ObjectStore(destination)
    (store.objects / "invalid-name").write_bytes(b"bad")
    opaque = next(
        item for item in build_index(store, refresh=True).objects if isinstance(item, IndexedOpaque)
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
    assert not (tmp_path / "missing").exists()

    store = ObjectStore(tmp_path / "limited")
    store.publish_json({"opaque": 1})
    partial = build_index(store, refresh=False, max_objects=0)
    assert partial.scan_incomplete
    assert any(issue.code == "scan_incomplete" for issue in partial.issues)
    complete = build_index(store, refresh=True, max_objects=0, max_bytes=0)
    assert not complete.scan_incomplete
    assert len(complete.objects) == 1


def test_non_writable_cache_is_diagnostic_but_does_not_hide_runs(
    review_fixture: ReviewFixture,
) -> None:
    root = review_fixture.store.root
    original_mode = root.stat().st_mode
    try:
        root.chmod(0o555)
        if os.access(root, os.W_OK):
            pytest.skip("process can bypass directory write permissions")
        index = build_index(review_fixture.store, refresh=True)
        assert not (root / "review-index.json").exists()
    finally:
        root.chmod(original_mode)

    assert any(run.manifest_ref == review_fixture.manifest_ref for run in index.runs)
    assert any(issue.code == "cache_write" for issue in index.issues)


def test_unreadable_object_directory_reports_one_issue(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "unreadable")
    store.publish_json({"opaque": True})
    original_mode = store.objects.stat().st_mode
    try:
        store.objects.chmod(0o000)
        if os.access(store.objects, os.R_OK):
            pytest.skip("process can bypass directory read permissions")
        index = build_index(store)
    finally:
        store.objects.chmod(original_mode)

    assert index.objects == ()
    assert index.runs == ()
    assert [issue.code for issue in index.issues] == ["root_unreadable"]


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
