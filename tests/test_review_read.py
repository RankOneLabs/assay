from __future__ import annotations

import pytest
from review_fixture import ReviewFixture, materialize_review_fixture

from assay.review.index import build_index
from assay.review.read import ReviewReader


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
        for verdict in cell.verdicts
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
