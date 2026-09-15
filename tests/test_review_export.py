from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import cast
from urllib.parse import quote

import pytest
from review_fixture import HOSTILE_STRINGS, ReviewFixture, materialize_review_fixture

from assay.review import export as review_export
from assay.review import read as review_read
from assay.review.export import (
    ExportError,
    build_export_data,
    compute_export_budget,
    export_review,
)
from assay.review.model import JSONValue, canonical_view_json
from assay.store import ObjectStore


@pytest.fixture(scope="module")
async def fixture(tmp_path_factory: pytest.TempPathFactory) -> ReviewFixture:
    return await materialize_review_fixture(tmp_path_factory.mktemp("static-export"))


def _embedded(path: Path) -> dict[str, object]:
    html = path.read_text(encoding="utf-8")
    match = re.search(
        r'<script id="assay-review-data" type="application/json" '
        r"data-assay-review>(.*?)</script>",
        html,
        re.DOTALL,
    )
    assert match is not None
    return cast(dict[str, object], json.loads(match.group(1)))


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _strings(child)]
    if isinstance(value, list):
        return [item for child in value for item in _strings(child)]
    return []


def test_manifest_export_is_deterministic_self_contained_and_bundle_equivalent(
    fixture: ReviewFixture, tmp_path: Path
) -> None:
    unrelated_ref = str(
        fixture.store.publish_json({"unrelated_host_path": str(fixture.store.root)})
    )
    first = export_review(fixture.store, fixture.manifest_ref, tmp_path / "first.html")
    second = export_review(fixture.store, fixture.manifest_ref, tmp_path / "second.html")
    bundled = export_review(fixture.bundle, fixture.manifest_ref, tmp_path / "bundle.html")

    assert first.read_bytes() == second.read_bytes() == bundled.read_bytes()
    html = first.read_text(encoding="utf-8")
    assert not re.search(r"\b(?:src|href)=[\"'](?!#)", html, re.IGNORECASE)
    assert str(fixture.store.root) not in html
    assert unrelated_ref not in html

    data = _embedded(first)
    assert data["schema_version"] == "assay-review-export/0.1.0"
    assert data["root_ref"] == fixture.manifest_ref
    assert data["store"]["root"] is None  # type: ignore[index]
    assert data["capabilities"] == {"recompute": False, "refresh": False, "verify": False}
    recovered = _strings(data)
    for hostile in HOSTILE_STRINGS:
        assert any(hostile in value for value in recovered)
    assert "</script><script>" not in html
    assert "</ScRiPt>" not in html
    assert "\u2028" not in html and "\u2029" not in html

    views = data["views"]
    assert isinstance(views, dict)
    for cell_id, outcome_ref in fixture.result.manifest.execution_records.items():
        outcome = json.loads(fixture.bundle.read_bytes(outcome_ref))
        cell_key = (
            f"/api/runs/{quote(fixture.manifest_ref, safe='')}"
            f"/cells/{quote(cell_id, safe='')}"
        )
        cell = views[cell_key]
        assert isinstance(cell, dict)
        assert cell["started_at"] == outcome["started_at"]
        assert cell["completed_at"] == outcome["completed_at"]


def test_budget_counts_raw_base64_and_canonical_view_bytes() -> None:
    closure = {"first": b"abc", "second": b"12345"}
    views: dict[str, JSONValue] = {"/api/store": {"label": "evidence"}}

    budget = compute_export_budget(closure, views)

    raw_bytes = 3 + 5
    base64_bytes = 4 + 8
    assert budget == raw_bytes + base64_bytes + len(canonical_view_json(views))


def test_pairs_use_ordered_api_paths_and_reference_cell_views(
    fixture: ReviewFixture,
) -> None:
    data = build_export_data(fixture.bundle, fixture.manifest_ref)
    prefix = f"/api/runs/{quote(fixture.manifest_ref, safe='')}/pairs/"
    pair_keys = [key for key in data.views if key.startswith(prefix)]

    assert pair_keys
    assert all("?reference=" in key and "&candidate=" in key for key in pair_keys)
    for key in pair_keys:
        pair = data.views[key]
        assert isinstance(pair, dict)
        for side in ("reference_cells", "candidate_cells"):
            cell_keys = pair[side]
            assert isinstance(cell_keys, list) and cell_keys
            assert all(
                isinstance(cell_key, str) and cell_key in data.views
                for cell_key in cell_keys
            )


def test_report_study_with_other_arm_names_has_explicit_pair_routes(
    fixture: ReviewFixture,
) -> None:
    report_ref = fixture.studies.report_refs["scalar"]
    data = build_export_data(fixture.studies.report_bundles["scalar"], report_ref)
    pair_keys = [key for key in data.views if "/pairs/" in key]

    assert any("?reference=reference&candidate=candidate" in key for key in pair_keys)
    assert any("?reference=candidate&candidate=reference" in key for key in pair_keys)


def test_report_export_contains_only_selected_report_and_all_pinned_runs(
    fixture: ReviewFixture, tmp_path: Path
) -> None:
    report_ref = fixture.studies.report_refs["scalar"]
    output = export_review(fixture.store, report_ref, tmp_path / "report.html")
    bundled = export_review(
        fixture.studies.report_bundles["scalar"], report_ref, tmp_path / "report-bundle.html"
    )
    assert output.read_bytes() == bundled.read_bytes()
    data = _embedded(output)
    views = data["views"]
    assert isinstance(views, dict)
    report_keys = [key for key in views if key.startswith("/api/reports/")]
    assert report_keys == [f"/api/reports/{quote(report_ref, safe='')}"]
    report = views[report_keys[0]]
    assert isinstance(report, dict)
    manifests = report["summary"]["manifest_refs"]
    for manifest_ref in manifests:
        assert f"/api/runs/{quote(manifest_ref, safe='')}" in views
    assert report["summary"]["recomputable"] is False
    assert report["summary"]["recompute_disabled_reason"] == (
        "Requires the local Assay server"
    )


@pytest.mark.parametrize("damage", ["manifest", "evaluation"])
def test_corrupt_closure_fails_with_code_and_ref_without_output(
    fixture: ReviewFixture, tmp_path: Path, damage: str
) -> None:
    destination = tmp_path / f"{damage}.html"
    expected_ref = (
        fixture.manifest_ref
        if damage == "manifest"
        else next(iter(fixture.result.manifest.evaluation_records.values()))
    )

    with pytest.raises(ExportError) as caught:
        export_review(fixture.damaged_stores[damage], fixture.manifest_ref, destination)

    assert caught.value.code == "integrity_error"
    assert caught.value.ref == expected_ref
    assert expected_ref in str(caught.value)
    assert not destination.exists()


def test_budget_overflow_leaves_no_output(
    fixture: ReviewFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "oversize.html"
    monkeypatch.setattr(review_export, "MAX_EXPORT_BYTES", 1)

    with pytest.raises(ExportError) as caught:
        export_review(fixture.bundle, fixture.manifest_ref, destination)

    assert caught.value.code == "export_budget_exceeded"
    assert caught.value.ref == fixture.manifest_ref
    assert not destination.exists()


def test_budget_caps_the_complete_serialized_document(
    fixture: ReviewFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = build_export_data(fixture.bundle, fixture.manifest_ref)
    document_size = len(review_export._document(data))
    destination = tmp_path / "complete-document-overflow.html"
    monkeypatch.setattr(review_export, "compute_export_budget", lambda *_args: 0)
    monkeypatch.setattr(review_export, "MAX_EXPORT_BYTES", document_size - 1)

    with pytest.raises(ExportError, match="export_budget_exceeded"):
        export_review(fixture.bundle, fixture.manifest_ref, destination)

    assert not destination.exists()


def test_preview_download_and_diff_limits_are_retained(
    fixture: ReviewFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(review_read, "MAX_PREVIEW_BYTES", 16)
    monkeypatch.setattr(review_read, "MAX_DIFF_BYTES", 16)
    monkeypatch.setattr(review_export, "MAX_DOWNLOAD_BYTES", 16)

    data = build_export_data(fixture.bundle, fixture.manifest_ref)

    bounded = [item for item in data.objects.values() if item.preview.truncated]
    assert bounded
    assert all(item.download_base64 is None for item in bounded)
    assert all("exceeds 8 MiB" in (item.download_unavailable_reason or "") for item in bounded)
    pairs = [value for key, value in data.views.items() if "/pairs/" in key]
    reasons: list[str] = []
    for pair in pairs:
        if isinstance(pair, dict):
            treatment = pair.get("treatment_diff")
            if isinstance(treatment, dict):
                reasons.append(str(treatment.get("unavailable_reason", "")))
    assert any(reason.startswith("diff suppressed") for reason in reasons)


def test_missing_closure_object_names_ref_and_leaves_no_output(
    fixture: ReviewFixture, tmp_path: Path
) -> None:
    store_path = tmp_path / "missing-store"
    shutil.copytree(fixture.bundle.root, store_path)
    store = ObjectStore(store_path)
    missing_ref = fixture.result.manifest.plan_ref
    (store.objects / missing_ref.removeprefix("sha256:")).unlink()
    destination = tmp_path / "missing.html"

    with pytest.raises(ExportError) as caught:
        export_review(store, fixture.manifest_ref, destination)

    assert caught.value.code == "missing_object"
    assert caught.value.ref == missing_ref
    assert missing_ref in str(caught.value)
    assert str(store.root) not in str(caught.value)
    assert not destination.exists()


def test_binary_extension_leaf_is_embedded(fixture: ReviewFixture, tmp_path: Path) -> None:
    store_path = tmp_path / "binary-store"
    shutil.copytree(fixture.bundle.root, store_path)
    store = ObjectStore(store_path)
    binary = b"\x00\xff\x80opaque"
    binary_ref = str(store.publish_bytes(binary))
    coordinate, outcome_ref = next(iter(fixture.result.manifest.execution_records.items()))
    outcome = json.loads(store.read_bytes(outcome_ref))
    output = json.loads(store.read_bytes(outcome["output_ref"]))
    output["assay_object_refs"] = [binary_ref]
    outcome["output_ref"] = str(store.publish_json(output))
    rewritten_outcome = str(store.publish_json(outcome))
    manifest = json.loads(store.read_bytes(fixture.manifest_ref))
    manifest["execution_records"][coordinate] = rewritten_outcome
    rewritten_manifest = str(store.publish_json(manifest))

    data = build_export_data(store, rewritten_manifest)

    embedded = data.objects[binary_ref]
    assert embedded.preview.kind == "binary"
    assert embedded.download_base64 == base64.b64encode(binary).decode("ascii")


def test_existing_destination_is_refused(fixture: ReviewFixture, tmp_path: Path) -> None:
    destination = tmp_path / "existing.html"
    destination.write_bytes(b"keep me")

    with pytest.raises(ExportError, match="destination_exists"):
        export_review(fixture.bundle, fixture.manifest_ref, destination)

    assert destination.read_bytes() == b"keep me"


def test_concurrent_destination_is_not_replaced(
    fixture: ReviewFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "concurrent.html"

    def competing_publish(source: str, target: str | Path) -> None:
        del source
        Path(target).write_bytes(b"concurrent winner")
        raise FileExistsError

    monkeypatch.setattr(os, "link", competing_publish)

    with pytest.raises(ExportError, match="destination_exists"):
        export_review(fixture.bundle, fixture.manifest_ref, destination)

    assert destination.read_bytes() == b"concurrent winner"


def test_export_import_and_full_operation_do_not_require_fastapi(
    fixture: ReviewFixture, tmp_path: Path
) -> None:
    destination = tmp_path / "core-only.html"
    program = (
        'import sys; sys.modules["fastapi"] = None; '
        "from assay.review.export import export_review; "
        "from assay.store import ObjectStore; "
        f"export_review(ObjectStore({str(fixture.bundle.root)!r}), "
        f"{fixture.manifest_ref!r}, {str(destination)!r})"
    )

    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr
    assert destination.is_file()
