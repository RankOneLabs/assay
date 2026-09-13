from __future__ import annotations

import json
from pathlib import Path

import pytest
from review_fixture import ReviewFixture, materialize_review_fixture

from assay.review.index import IndexedOpaque, classify_object
from assay.review.model import ReadIssue


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
