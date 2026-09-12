from __future__ import annotations

import json
from pathlib import Path

import pytest
from review_fixture import (
    HOSTILE_REPOSITORY_PATH,
    HOSTILE_STRINGS,
    HOSTILE_TEXT,
    ReviewFixture,
    materialize_review_fixture,
)

from assay.models import EvaluationFailure
from assay.verify import verify_bundle, verify_manifest


@pytest.fixture
async def fixture(tmp_path: Path) -> ReviewFixture:
    return await materialize_review_fixture(tmp_path)


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
