from __future__ import annotations

import json

import pytest
from review_fixture import (
    HOSTILE_REPOSITORY_PATH,
    HOSTILE_STRINGS,
    HOSTILE_TEXT,
    ReviewFixture,
    materialize_review_fixture,
)

from assay._version import __version__
from assay.models import EvaluationFailure, ReportConfig
from assay.report_engine import ReportError, build_report
from assay.verify import verify_bundle, verify_manifest


@pytest.fixture(scope="module")
async def fixture(tmp_path_factory: pytest.TempPathFactory) -> ReviewFixture:
    return await materialize_review_fixture(tmp_path_factory.mktemp("review-fixture"))


def test_primary_manifest_is_complete_and_verifies(fixture: ReviewFixture) -> None:
    assert fixture.result.manifest.status == "complete"
    assert verify_manifest(fixture.store, fixture.manifest_ref) == ()
    assert verify_bundle(fixture.bundle, fixture.manifest_ref) == ()


def test_ambiguity_and_execution_unavailability_are_distinct(fixture: ReviewFixture) -> None:
    records = [
        json.loads(fixture.store.read_bytes(ref))
        for ref in fixture.result.manifest.evaluation_records.values()
    ]
    failures = [
        EvaluationFailure.model_validate(record) for record in records if "error_type" in record
    ]
    ambiguous = [record for record in failures if record.error_type == "AmbiguousStructure"]
    unavailable = [record for record in failures if record.error_type == "ExecutionUnavailable"]
    assert len(ambiguous) == 1
    assert unavailable
    assert ambiguous[0].coordinate != unavailable[0].coordinate


def test_hostile_strings_cover_review_surfaces(fixture: ReviewFixture) -> None:
    payloads = [
        json.loads(fixture.store.read_bytes("sha256:" + path.name))
        for path in fixture.store.objects.iterdir()
    ]
    def strings(value: object) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            return [part for key, item in value.items() for part in strings(key) + strings(item)]
        if isinstance(value, list):
            return [part for item in value for part in strings(item)]
        return []

    stored_strings = [part for payload in payloads for part in strings(payload)]
    assert any(
        HOSTILE_TEXT in value.get("source", "") for value in payloads if isinstance(value, dict)
    )
    assert any(
        HOSTILE_REPOSITORY_PATH in value.get("repository", {})
        for value in payloads
        if isinstance(value, dict)
    )
    assert any(HOSTILE_TEXT in subject.label for subject in fixture.snapshot.subjects)
    assert any(
        (value.get("error_message") or "").endswith(HOSTILE_TEXT)
        for value in payloads
        if isinstance(value, dict)
    )
    assert all(any(hostile in value for value in stored_strings) for hostile in HOSTILE_STRINGS)


def test_damaged_variants_have_hash_mismatched_objects(fixture: ReviewFixture) -> None:
    assert set(fixture.damaged_stores) == {"manifest", "evaluation", "execution", "unexpected"}
    for store in fixture.damaged_stores.values():
        assert verify_bundle(store, fixture.manifest_ref)


def test_review_studies_cover_report_shapes_and_inference(fixture: ReviewFixture) -> None:
    studies = fixture.studies
    assert set(studies.reports) == {
        "scalar",
        "mapped_ordinal",
        "unmapped_ordinal",
        "classification",
    }
    for name, config in studies.report_configs.items():
        assert build_report(fixture.store, config) == studies.reports[name]
        assert verify_bundle(studies.report_bundles[name], studies.report_refs[name]) == ()
    comparisons = [report["comparisons"][0] for report in studies.reports.values()]
    assert any(item["n"] >= 10 and item["p_value"] is not None for item in comparisons)
    assert any(item["decision"] == "descriptive_only" for item in comparisons)
    assert studies.reports["unmapped_ordinal"]["comparisons"][0]["n"] == 12


def test_stale_engine_report_pins_unsupported_config(fixture: ReviewFixture) -> None:
    studies = fixture.studies
    stale_report = json.loads(fixture.store.read_bytes(studies.stale_report_ref))
    stale_config = json.loads(fixture.store.read_bytes(stale_report["config_ref"]))
    assert stale_report["config_ref"] == studies.stale_config_ref
    assert stale_config["engine_version"] != __version__
    with pytest.raises(ReportError, match="unsupported report engine version"):
        build_report(fixture.store, ReportConfig.model_validate(stale_config))
