from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import cast

import pytest
from review_fixture import ReviewFixture, materialize_review_fixture

from assay.report_engine import summarize_operating
from assay.review.index import build_index
from assay.review.model import JSONObject
from assay.review.read import ReviewReader, _persisted_cost
from assay.store import ObjectStore


@pytest.fixture(scope="module")
async def fixture(tmp_path_factory: pytest.TempPathFactory) -> ReviewFixture:
    return await materialize_review_fixture(tmp_path_factory.mktemp("cost-layer"))


def test_uncertain_accounting_is_never_summed_or_confused_with_measured_zero(
    tmp_path: Path,
) -> None:
    store = ObjectStore(tmp_path / "uncertain-store")
    detail_ref = str(
        store.publish_json(
            {
                "run_id": "run-1",
                "attempt": "worker:s:a:w0",
                "coverage": "uncertain",
                "pricing_catalog_ref": "sha256:" + "b" * 64,
                "pricing_assumptions": {},
                "configuration_ref": "sha256:" + "c" * 64,
            }
        )
    )
    operating_ref = str(
        store.publish_json(
            {
                "record_schema": "paa-operating-record/0.1.0-draft",
                "record_id": "run-1:worker:s:a:w0",
                "usage": {"input_tokens": 3},
                "price": None,
                "source_references": [detail_ref],
            }
        )
    )
    summary = summarize_operating(store, [operating_ref])
    assert summary["coverage"] == "uncertain"
    assert summary["amounts"] == {}
    assert summary["attempts"] == 1


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


@pytest.mark.parametrize(
    "costs",
    [
        None,
        [],
        "unavailable",
        42,
        {"coverage_counts": [], "amounts": {}},
        {"coverage_counts": {}, "amounts": []},
        {"coverage_counts": {"measured": "bad"}, "amounts": {}},
        {"coverage_counts": {}, "amounts": {"USD": "nan"}},
        {"coverage_counts": {}, "amounts": {}, "attempts": "bad"},
    ],
)
def test_malformed_persisted_costs_become_issues(costs: object) -> None:
    projected = _persisted_cost(costs, ())

    assert projected.coverage == "unavailable"
    assert projected.amounts == {}
    assert [issue.code for issue in projected.issues] == ["invalid_accounting"]


@pytest.mark.parametrize(
    "schema_fields",
    [
        {},
        {"record_schema": None},
        {"record_schema": 42},
        {"record_schema": False},
        {"record_schema": []},
        {"record_schema": {}},
    ],
    ids=["missing", "null", "number", "boolean", "array", "object"],
)
def test_invalid_accounting_schema_leaves_run_browsable(
    fixture: ReviewFixture,
    tmp_path: Path,
    schema_fields: JSONObject,
) -> None:
    shutil.copytree(fixture.bundle.root, tmp_path / "store")
    store = ObjectStore(tmp_path / "store")
    manifest = fixture.result.manifest.model_dump(mode="json")
    attempt, original_ref = next(iter(manifest["operating_records"].items()))
    accounting = json.loads(store.read_bytes(original_ref))
    del accounting["record_schema"]
    accounting.update(schema_fields)
    invalid_ref = str(store.publish_json(accounting))
    manifest["operating_records"][attempt] = invalid_ref
    manifest_ref = str(store.publish_json(manifest))

    reader = ReviewReader(store, build_index(store))
    baseline = reader.run(fixture.manifest_ref)
    detail = reader.run(manifest_ref)
    assert detail.summary.cells_succeeded == baseline.summary.cells_succeeded
    assert detail.summary.cost.attempts == baseline.summary.cost.attempts - 1
    assert detail.summary.cost.partial
    issue = next(
        issue for issue in detail.summary.cost.issues if issue.code == "invalid_accounting"
    )
    assert issue.ref == invalid_ref
    assert issue in detail.summary.issues
