from __future__ import annotations

import json

import pytest
from review_fixture import ReviewFixture, materialize_review_fixture

from assay.review.index import build_index
from assay.review.read import ReviewReader


@pytest.fixture(scope="module")
async def fixture(tmp_path_factory: pytest.TempPathFactory) -> ReviewFixture:
    return await materialize_review_fixture(tmp_path_factory.mktemp("report-layer"))


def test_reports_render_the_exact_persisted_object(fixture: ReviewFixture) -> None:
    reader = ReviewReader(fixture.store, build_index(fixture.store))
    for report_ref in fixture.studies.report_refs.values():
        persisted = json.loads(fixture.store.read_bytes(report_ref))
        assert reader.report(report_ref).report == persisted


def test_stale_report_renders_without_recomputation(
    fixture: ReviewFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("reading invoked report recomputation")

    monkeypatch.setattr("assay.review.read.build_report", forbidden)
    monkeypatch.setattr("assay.review.read.verify_report", forbidden)
    monkeypatch.setattr("assay.review.read.verify_bundle", forbidden)
    reader = ReviewReader(fixture.store, build_index(fixture.store))
    detail = reader.report(fixture.studies.stale_report_ref)
    assert detail.report == json.loads(fixture.store.read_bytes(fixture.studies.stale_report_ref))
    assert not detail.summary.recomputable
    assert detail.summary.recompute_disabled_reason


def test_all_persisted_metric_shapes_remain_available(fixture: ReviewFixture) -> None:
    reader = ReviewReader(fixture.store, build_index(fixture.store))
    details = {name: reader.report(ref) for name, ref in fixture.studies.report_refs.items()}
    assert set(details) == {
        "scalar",
        "mapped_ordinal",
        "unmapped_ordinal",
        "classification",
    }
    assert all(detail.comparisons for detail in details.values())
    ordinal = details["unmapped_ordinal"]
    assert ordinal.comparisons[0].values["categories"] == list(
        fixture.studies.report_configs["unmapped_ordinal"].categories
    )


def test_descriptive_only_and_null_statistics_are_preserved(
    fixture: ReviewFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("display must not compute statistics")

    monkeypatch.setattr("assay.review.read.build_report", forbidden)
    ref = fixture.studies.report_refs["scalar"]
    persisted = json.loads(fixture.store.read_bytes(ref))
    comparison = persisted["comparisons"][0]
    assert comparison["decision"] == "descriptive_only"
    assert comparison["confidence_interval"] is None
    assert comparison["p_value"] is None
    detail = ReviewReader(fixture.store, build_index(fixture.store)).report(ref)
    assert detail.comparisons[0].values == comparison
    assert detail.comparisons[0].values["confidence_interval"] is None
    assert detail.comparisons[0].values["p_value"] is None
    assert detail.comparisons[0].values["interval_adjustment"] == comparison["interval_adjustment"]
    assert detail.report["profile"] == persisted["profile"]
    assert persisted["profile"]["min_subjects"] == 10
    assert detail.report == persisted
