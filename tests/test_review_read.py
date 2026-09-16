from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from review_fixture import ReviewFixture, materialize_review_fixture

from assay.review.index import build_index
from assay.review.read import ReviewReader, verify
from assay.store import ObjectStore
from assay.verify import verify_manifest


@pytest.fixture(scope="module")
async def fixture(tmp_path_factory: pytest.TempPathFactory) -> ReviewFixture:
    return await materialize_review_fixture(tmp_path_factory.mktemp("read-layer"))


def test_run_preserves_failures_exclusions_and_evaluation_missingness(
    fixture: ReviewFixture,
) -> None:
    reader = ReviewReader(fixture.store, build_index(fixture.store))
    detail = reader.run(fixture.manifest_ref)

    failure = next(cell for cell in detail.cells if cell.error_type == "InjectedFailure")
    assert failure.status == "failed"
    excluded = [cell for cell in detail.cells if cell.status == "excluded"]
    assert excluded
    assert all(cell.exclusion and cell.exclusion.classification == "fixture" for cell in excluded)

    ambiguous = [
        evaluation
        for cell in detail.cells
        for evaluation in reader.cell(detail.summary.run_key, cell.cell_id).evaluations
        if evaluation.error_type == "AmbiguousStructure"
    ]
    assert len(ambiguous) == 1
    assert ambiguous[0].status == "missing"
    assert ambiguous[0].verdict is None


def test_pair_retains_excluded_repeat_placeholders(fixture: ReviewFixture) -> None:
    reader = ReviewReader(fixture.store, build_index(fixture.store))
    detail = reader.run(fixture.manifest_ref)
    excluded = next(cell for cell in detail.cells if cell.status == "excluded")
    pair = reader.pair(
        fixture.manifest_ref,
        excluded.subject_id,
        reference_arm="clean",
        candidate_arm="inconsistent",
    )
    assert len(pair.reference_cells) == len(pair.candidate_cells) == 2
    assert all(cell.summary.status == "excluded" for cell in pair.candidate_cells)


def test_child_integrity_error_names_ref_without_store_path(fixture: ReviewFixture) -> None:
    store = fixture.damaged_stores["execution"]
    reader = ReviewReader(store, build_index(fixture.bundle))
    detail = reader.run(fixture.manifest_ref)
    issues = [issue for cell in detail.cells for issue in cell.issues]
    issue = next(issue for issue in issues if issue.code == "integrity_error")
    assert issue.ref is not None and issue.ref in issue.message
    assert str(store.root) not in issue.message


def test_corrupt_evaluation_is_reported_at_run_level(fixture: ReviewFixture) -> None:
    store = fixture.damaged_stores["evaluation"]
    detail = ReviewReader(store, build_index(fixture.bundle)).run(fixture.manifest_ref)
    ref = next(iter(fixture.result.manifest.evaluation_records.values()))
    assert any(
        issue.code == "integrity_error" and issue.ref == ref for issue in detail.summary.issues
    )
    assert detail.summary.evaluations_invalid == 1


@pytest.mark.parametrize("missing", ["plan", "snapshot", "outcome"])
def test_missing_children_preserve_run(
    fixture: ReviewFixture,
    tmp_path: Path,
    missing: str,
) -> None:
    shutil.copytree(fixture.bundle.root, tmp_path / "store")
    store = ObjectStore(tmp_path / "store")
    index = build_index(store)
    plan_ref = fixture.result.manifest.plan_ref
    plan = json.loads(store.read_bytes(plan_ref))
    coordinate, outcome_ref = next(iter(fixture.result.manifest.execution_records.items()))
    ref = {"plan": plan_ref, "snapshot": plan["snapshot_ref"], "outcome": outcome_ref}[missing]
    (store.objects / ref.removeprefix("sha256:")).unlink()
    detail = ReviewReader(store, index).run(fixture.manifest_ref)
    assert detail.summary.manifest_ref == fixture.manifest_ref
    assert any(
        issue.code == "missing_object" and issue.ref == ref for issue in detail.summary.issues
    )
    if missing == "plan":
        assert detail.summary.cells_total is None
        assert detail.summary.cells_missing is None
        assert detail.summary.snapshot_ref is None
        assert detail.summary.worker_repeats is None
    elif missing == "snapshot":
        assert detail.summary.subjects is None
        assert detail.summary.arms is None
        assert detail.subjects == ()
        assert detail.summary.cells_total == len(plan["cells"])
    else:
        cell = next(cell for cell in detail.cells if cell.cell_id == coordinate)
        assert cell.status == "invalid"
        assert cell.record_refs == (outcome_ref,)
        assert cell.error_type is None
        assert any(cell.status == "succeeded" for cell in detail.cells)
    assert ReviewReader(fixture.bundle, index).run(fixture.manifest_ref).summary.cells_invalid == 0


def test_recorded_prompt_keeps_trace_provenance(
    fixture: ReviewFixture,
    tmp_path: Path,
) -> None:
    shutil.copytree(fixture.bundle.root, tmp_path / "store")
    store = ObjectStore(tmp_path / "store")
    manifest = fixture.result.manifest.model_dump(mode="json")
    coordinate, ref = next(iter(manifest["execution_records"].items()))
    outcome = json.loads(store.read_bytes(ref))
    prompt = "A recorded user prompt different from the governed instruction."
    trace_ref = str(store.publish_json({"prompt": prompt}))
    outcome["trace_ref"] = trace_ref
    manifest["execution_records"][coordinate] = str(store.publish_json(outcome))
    manifest_ref = str(store.publish_json(manifest))
    detail = ReviewReader(store, build_index(store)).cell(manifest_ref, coordinate)
    assert detail.recorded_prompt == prompt
    assert detail.recorded_prompt_ref == trace_ref
    assert detail.trace_ref == trace_ref
    assert detail.input_ref == outcome["input_ref"]
    assert detail.input_preview.instruction != prompt
    artifact = json.loads(store.read_bytes(outcome["input_ref"]))
    assert detail.input_preview.instruction == artifact["task"]["instruction"]
    assert detail.input_preview.files == artifact["repository"]
    assert detail.input_preview.artifact is not None
    assert json.loads(detail.input_preview.artifact.text or "null") == artifact


def test_verify_missing_closure_object_names_ref_and_referrer(
    fixture: ReviewFixture,
    tmp_path: Path,
) -> None:
    shutil.copytree(fixture.bundle.root, tmp_path / "store")
    store = ObjectStore(tmp_path / "store")
    plan_ref = fixture.result.manifest.plan_ref
    ref = json.loads(store.read_bytes(plan_ref))["snapshot_ref"]
    (store.objects / ref.removeprefix("sha256:")).unlink()
    result = verify(store, fixture.manifest_ref)
    assert result.status == "failed"
    failure = next(item for item in result.failures if item.code == "missing_object")
    assert ref in failure.message
    assert plan_ref in failure.message
    assert all(str(store.root) not in item.message for item in result.failures)


def test_incomplete_run_verifies_as_partial(fixture: ReviewFixture) -> None:
    # The fixture's manifest is already honestly incomplete (its one injected
    # execution failure leaves an evaluation unavailable); this additionally
    # drops an operating record to exercise that second missing-coordinate
    # shape, folding it into the pre-existing missing set rather than
    # replacing it.
    manifest = fixture.result.manifest.model_dump(mode="json")
    missing = next(iter(manifest["operating_records"]))
    del manifest["operating_records"][missing]
    manifest["missing_coordinates"] = sorted({*manifest["missing_coordinates"], missing})
    manifest["status"] = "incomplete"
    ref = str(fixture.store.publish_json(manifest))
    assert [failure.code for failure in verify_manifest(fixture.store, ref)] == ["incomplete_run"]
    result = verify(fixture.store, ref)
    assert result.status == "partial"
    assert result.failures == ()
    assert "plan completeness" in result.checks
