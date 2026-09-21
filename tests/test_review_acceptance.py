from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Literal

import httpx
import pytest
from review_fixture import ReviewFixture, materialize_review_fixture

from assay.review.export import export_review
from assay.review.read import closure, verify
from assay.review.server import create_app
from assay.store import ObjectStore
from assay.verify import verify_bundle

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_REVIEW_CALLS = (
    "execute_plan",
    "compile_plan",
    "persist_report",
    # The review layer must never be able to trigger a paid Pier dispatch
    # either -- these three are the only functions that ever set
    # allow_paid=True against a real bridge (pier_qualification.pier_experiment).
    "run_pier_full",
    "run_pier_smoke",
    "run_pier_qualification",
)


@pytest.fixture(scope="module")
async def fixture(tmp_path_factory: pytest.TempPathFactory) -> ReviewFixture:
    return await materialize_review_fixture(tmp_path_factory.mktemp("review-acceptance"))


def _object_bytes(store: ObjectStore) -> dict[str, bytes]:
    return {
        path.name: path.read_bytes()
        for path in sorted(store.objects.iterdir())
        if path.is_file()
    }


async def _exercise_server(store: ObjectStore, root_ref: str) -> None:
    app = create_app(store)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        shell = await client.get("/")
        summary = await client.get("/api/store")
        run = await client.get(f"/api/runs/{root_ref}")
    assert shell.status_code == 200
    assert summary.status_code == 200
    assert run.status_code == 200


async def test_serve_and_export_leave_source_and_bundle_objects_unchanged(
    fixture: ReviewFixture, tmp_path: Path
) -> None:
    stores = (fixture.store, fixture.bundle)
    before = [_object_bytes(store) for store in stores]

    for index, store in enumerate(stores):
        await _exercise_server(store, fixture.manifest_ref)
        export_review(store, fixture.manifest_ref, tmp_path / f"review-{index}.html")

    assert [_object_bytes(store) for store in stores] == before
    assert [f.code for f in verify_bundle(fixture.bundle, fixture.manifest_ref)] == [
        "incomplete_run"
    ]


def _exact_bundle(source: ObjectStore, root_ref: str, destination: Path) -> ObjectStore:
    refs, failures = closure(source, root_ref)
    assert failures == []
    bundle = ObjectStore(destination)
    for ref in sorted(refs):
        bundle.publish_bytes(source.read_bytes(ref))
    return bundle


async def test_verification_scopes_reports_and_post_only_actions(
    fixture: ReviewFixture, tmp_path: Path
) -> None:
    fixture.store.publish_json({"unrelated": "object outside every selected closure"})

    root = verify(fixture.store, fixture.manifest_ref, "root")
    overfull_bundle = verify(fixture.store, fixture.manifest_ref, "bundle")
    exact_root = verify(fixture.bundle, fixture.manifest_ref, "root")
    exact_bundle = verify(fixture.bundle, fixture.manifest_ref, "bundle")
    # The fixture's one injected execution failure makes the manifest
    # honestly incomplete; "partial" is the passing-but-incomplete verdict
    # for that, distinct from "failed" (which is reserved for anything
    # beyond the expected, accounted "incomplete_run" flag).
    assert root.status == "partial" and root.failures == ()
    assert overfull_bundle.status == "failed"
    assert {failure.code for failure in overfull_bundle.failures} == {"bundle_closure"}
    assert exact_root.status == exact_bundle.status == "partial"

    report_ref = fixture.studies.report_refs["scalar"]
    report_bundle = fixture.studies.report_bundles["scalar"]
    for result in (
        verify(fixture.store, report_ref, "root"),
        verify(report_bundle, report_ref, "root"),
        verify(report_bundle, report_ref, "bundle"),
    ):
        assert result.status == "passed"
        assert "report recomputation" in result.checks
        assert result.failures == ()

    stale_ref = fixture.studies.stale_report_ref
    stale_bundle = _exact_bundle(fixture.store, stale_ref, tmp_path / "stale-bundle")
    scopes: tuple[Literal["root", "bundle"], ...] = ("root", "bundle")
    for scope in scopes:
        stale = verify(stale_bundle, stale_ref, scope)
        assert stale.status == "partial"
        assert stale.failures == ()
        assert stale.unsupported_reason is not None
        assert "reference closure" in stale.checks
        assert "report recomputation" not in stale.checks
        assert ("bundle object set" in stale.checks) is (scope == "bundle")

    corrupt_path = tmp_path / "corrupt-stale"
    shutil.copytree(stale_bundle.root, corrupt_path)
    corrupt = ObjectStore(corrupt_path)
    (corrupt.objects / stale_ref.removeprefix("sha256:")).write_bytes(b"corrupt")
    for scope in scopes:
        assert verify(corrupt, stale_ref, scope).status == "failed"

    app = create_app(fixture.store)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        recompute = await client.get(f"/api/reports/{report_ref}/recompute")
        verification = await client.get(f"/api/verify/{fixture.manifest_ref}")
    assert recompute.status_code == verification.status_code == 405


def test_review_layer_has_no_execution_or_report_persistence_calls() -> None:
    violations: list[str] = []
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--", "src/assay/review/", "web/"],
        cwd=ROOT, capture_output=True, check=True, text=True,
    ).stdout.split("\0")
    assert any(tracked), "review invariant must inspect tracked files"
    for relative in filter(None, tracked):
        text = (ROOT / relative).read_text(encoding="utf-8", errors="replace")
        for forbidden in FORBIDDEN_REVIEW_CALLS:
            if forbidden in text:
                violations.append(f"{relative}: {forbidden}")
    assert violations == []
