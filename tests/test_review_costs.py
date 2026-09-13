from __future__ import annotations

from typing import cast

import pytest
from review_fixture import ReviewFixture, materialize_review_fixture

from assay.review.index import build_index
from assay.review.model import JSONObject
from assay.review.read import ReviewReader


@pytest.fixture(scope="module")
async def fixture(tmp_path_factory: pytest.TempPathFactory) -> ReviewFixture:
    return await materialize_review_fixture(tmp_path_factory.mktemp("cost-layer"))


def test_unavailable_accounting_never_becomes_zero(fixture: ReviewFixture) -> None:
    detail = ReviewReader(fixture.store, build_index(fixture.store)).run(fixture.manifest_ref)
    if detail.summary.cost.coverage == "unavailable":
        assert detail.summary.cost.amounts == {}
    assert 0.0 not in detail.summary.cost.amounts.values()


def test_cost_attempts_are_bounded_by_honest_expectation(fixture: ReviewFixture) -> None:
    detail = ReviewReader(fixture.store, build_index(fixture.store)).run(fixture.manifest_ref)
    cost = detail.summary.cost
    assert cost.expected_attempts is None or cost.attempts <= cost.expected_attempts
    assert cost.unaccounted_attempts is None or cost.unaccounted_attempts >= 0


def test_report_costs_are_projected_without_recalculation(fixture: ReviewFixture) -> None:
    reader = ReviewReader(fixture.store, build_index(fixture.store))
    for ref in fixture.studies.report_refs.values():
        detail = reader.report(ref)
        persisted = cast(JSONObject, detail.report["costs"])
        assert detail.costs.amounts == persisted["amounts"]
        assert detail.costs.by_stage_arm == persisted["by_stage_arm"]
