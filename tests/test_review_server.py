from __future__ import annotations

import shutil
from pathlib import Path

import httpx
import pytest
from review_fixture import ReviewFixture, materialize_review_fixture

from assay.review import server
from assay.review.index import build_index
from assay.review.model import canonical_view_json
from assay.review.read import ReviewReader
from assay.review.server import OBJECT_LIMIT, TRUNCATION_MARKER, create_app, validate_bind_host
from assay.store import ObjectStore


@pytest.fixture(scope="module")
async def fixture(tmp_path_factory: pytest.TempPathFactory) -> ReviewFixture:
    return await materialize_review_fixture(tmp_path_factory.mktemp("review-server"))


def client_for(store: ObjectStore, **kwargs: object) -> httpx.AsyncClient:
    app = create_app(store, **kwargs)  # type: ignore[arg-type]
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost")


def copy_store(store: ObjectStore, destination: Path) -> ObjectStore:
    shutil.copytree(store.root, destination)
    return ObjectStore(destination)


async def test_store_refresh_uses_exporter_canonical_bytes(fixture: ReviewFixture) -> None:
    expected = canonical_view_json(
        ReviewReader(fixture.store, build_index(fixture.store, refresh=True)).store_summary()
    )
    async with client_for(fixture.store) as client:
        ordinary = await client.get("/api/store?refresh=true")
        response = await client.post("/api/store/refresh")
    assert ordinary.status_code == 200
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.content == expected


async def test_routes_are_views_over_the_reading_layer(fixture: ReviewFixture) -> None:
    index = build_index(fixture.store)
    reader = ReviewReader(fixture.store, index)
    detail = reader.run(fixture.manifest_ref)
    cell_id = detail.cells[0].cell_id
    subject_id = detail.subjects[0].id
    report_ref = fixture.studies.report_refs["scalar"]
    async with client_for(fixture.store) as client:
        responses = {
            "run": await client.get(f"/api/runs/{fixture.manifest_ref}"),
            "cell": await client.get(f"/api/runs/{fixture.manifest_ref}/cells/{cell_id}"),
            "pair": await client.get(
                f"/api/runs/{fixture.manifest_ref}/pairs/{subject_id}",
                params={"reference": "clean", "candidate": "inconsistent"},
            ),
            "ambiguous": await client.get(f"/api/runs/{fixture.manifest_ref}/ambiguous"),
            "ambiguities": await client.get("/api/ambiguities"),
            "reports": await client.get("/api/reports"),
            "report": await client.get(f"/api/reports/{report_ref}"),
        }
    assert responses["run"].content == canonical_view_json(reader.run(fixture.manifest_ref))
    assert responses["cell"].content == canonical_view_json(
        reader.cell(fixture.manifest_ref, cell_id)
    )
    assert responses["pair"].content == canonical_view_json(
        reader.pair(fixture.manifest_ref, subject_id, "clean", "inconsistent")
    )
    assert responses["ambiguous"].content == canonical_view_json(
        reader.ambiguities(fixture.manifest_ref)
    )
    assert responses["ambiguities"].content == canonical_view_json(reader.ambiguities())
    assert responses["reports"].content == canonical_view_json(reader.store_summary().reports)
    assert responses["report"].content == canonical_view_json(reader.report(report_ref))


async def test_actions_are_post_only_and_return_read_layer_results(
    fixture: ReviewFixture,
) -> None:
    current = fixture.studies.report_refs["scalar"]
    stale = fixture.studies.stale_report_ref
    async with client_for(fixture.store) as client:
        assert (await client.get(f"/api/reports/{current}/recompute")).status_code == 405
        assert (await client.get(f"/api/verify/{fixture.manifest_ref}")).status_code == 405
        matched = await client.post(f"/api/reports/{current}/recompute")
        unsupported = await client.post(f"/api/reports/{stale}/recompute")
        verified = await client.post(
            f"/api/verify/{fixture.manifest_ref}", params={"scope": "root"}
        )
    assert matched.json()["status"] == "matched"
    assert matched.json()["matched"] is True
    assert matched.json()["stored_digest"] == matched.json()["recomputed_digest"]
    assert unsupported.json()["status"] == "unsupported"
    assert unsupported.json()["reason"]
    # The fixture's one injected execution failure makes the manifest
    # honestly incomplete, which verifies as "partial" (accounted, not
    # broken), not "passed".
    assert verified.json()["status"] == "partial"


async def test_error_contract_and_api_fallback(fixture: ReviewFixture) -> None:
    unknown = "sha256:" + "0" * 64
    async with client_for(fixture.store) as client:
        malformed = await client.get("/api/runs/not:a:valid:key")
        missing = await client.get(f"/api/runs/{unknown}")
        bad_ref = await client.get("/api/reports/nope")
        bad_scope = await client.post(
            f"/api/verify/{fixture.manifest_ref}", params={"scope": "everything"}
        )
        fallback = await client.get("/api/does-not-exist")
    for response in (malformed, missing, bad_ref, bad_scope, fallback):
        body = response.json()
        assert set(body) == {"error"}
        assert set(body["error"]) == {"code", "message", "ref"}
    assert malformed.status_code == 400
    assert missing.status_code == 404
    assert bad_ref.status_code == 400
    assert bad_scope.status_code == 400
    assert fallback.status_code == 404
    assert fallback.headers["content-type"] == "application/json"


async def test_pair_returns_plan_unavailable_when_plan_is_unreachable(
    fixture: ReviewFixture, tmp_path: Path
) -> None:
    store = copy_store(fixture.store, tmp_path / "missing-plan")
    plan_ref = fixture.result.manifest.plan_ref
    (store.objects / plan_ref.removeprefix("sha256:")).unlink()
    subject_id = fixture.snapshot.subjects[0].id
    async with client_for(store) as client:
        response = await client.get(f"/api/runs/{fixture.manifest_ref}/pairs/{subject_id}")
    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "plan_unavailable",
            "message": "the run plan required for pairing is unavailable",
            "ref": plan_ref,
        }
    }


async def test_partial_child_response_carries_issues(
    fixture: ReviewFixture, tmp_path: Path
) -> None:
    store = copy_store(fixture.store, tmp_path / "damaged-child")
    app = create_app(store)
    cell_id, execution_ref = next(iter(fixture.result.manifest.execution_records.items()))
    (store.objects / execution_ref.removeprefix("sha256:")).write_bytes(b"damaged child")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        response = await client.get(f"/api/runs/{fixture.manifest_ref}/cells/{cell_id}")
    assert response.status_code == 200
    assert response.json()["summary"]["status"] == "invalid"
    assert response.json()["summary"]["issues"]
    assert response.json()["summary"]["issues"][0]["code"] == "integrity_error"


async def test_summary_routes_translate_newly_corrupt_root(
    fixture: ReviewFixture, tmp_path: Path
) -> None:
    store = copy_store(fixture.store, tmp_path / "corrupt-summary")
    app = create_app(store)
    (store.objects / fixture.manifest_ref.removeprefix("sha256:")).write_bytes(b"damaged")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        store_response = await client.get("/api/store")
        reports_response = await client.get("/api/reports")
        run_ambiguities = await client.get(
            f"/api/runs/{fixture.manifest_ref}/ambiguous"
        )
        ambiguities = await client.get("/api/ambiguities")
    for response in (store_response, reports_response, run_ambiguities, ambiguities):
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "corrupt_root"
    assert store_response.json()["error"]["ref"] is None
    assert reports_response.json()["error"]["ref"] is None
    assert run_ambiguities.json()["error"]["ref"] == fixture.manifest_ref
    assert ambiguities.json()["error"]["ref"] is None


async def test_object_passthrough_is_bounded_and_never_renderable(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "objects")
    text_ref = str(store.publish_bytes(b"<script>alert('no')</script>"))
    long_ref = str(store.publish_bytes(b"x" * (OBJECT_LIMIT + 1)))
    binary_ref = str(store.publish_bytes(b"\x00\xffpayload"))
    large_binary_ref = str(store.publish_bytes(b"\x00" + b"z" * OBJECT_LIMIT))
    async with client_for(store) as client:
        text = await client.get(f"/api/objects/{text_ref}")
        truncated = await client.get(f"/api/objects/{long_ref}")
        binary = await client.get(f"/api/objects/{binary_ref}")
        too_large = await client.get(f"/api/objects/{large_binary_ref}")
        malformed = await client.get("/api/objects/sha256:nope")
    assert text.headers["content-type"] == "text/plain; charset=utf-8"
    assert text.headers["x-content-type-options"] == "nosniff"
    assert text.content.startswith(b"<script>")
    assert len(truncated.content) == OBJECT_LIMIT
    assert truncated.content.endswith(TRUNCATION_MARKER)
    assert truncated.headers["x-assay-object-size"] == str(OBJECT_LIMIT + 1)
    assert truncated.headers["x-assay-truncated"] == "true"
    assert binary.content == b"\x00\xffpayload"
    assert binary.headers["content-disposition"].startswith("attachment;")
    assert too_large.status_code == 413
    assert too_large.headers["x-content-type-options"] == "nosniff"
    assert malformed.status_code == 400


async def test_object_read_is_memory_bounded_and_truncation_preserves_utf8(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ObjectStore(tmp_path / "bounded-objects")
    prefix_limit = OBJECT_LIMIT - len(TRUNCATION_MARKER)
    text_data = b"x" * (prefix_limit - 1) + "€".encode() + b"y" * len(TRUNCATION_MARKER)
    text_ref = str(store.publish_bytes(text_data))
    binary_ref = str(store.publish_bytes(b"\x00" + b"z" * OBJECT_LIMIT))
    app = create_app(store)

    def forbidden_read_bytes(_path: Path) -> bytes:
        raise AssertionError("object endpoint materialized the whole file")

    monkeypatch.setattr(Path, "read_bytes", forbidden_read_bytes)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        text = await client.get(f"/api/objects/{text_ref}")
        binary = await client.get(f"/api/objects/{binary_ref}")
    assert text.status_code == 200
    assert text.content.decode("utf-8").endswith(TRUNCATION_MARKER.decode())
    assert len(text.content) <= OBJECT_LIMIT
    assert binary.status_code == 413


async def test_hash_mismatch_never_returns_object_bytes(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "damaged")
    ref = str(store.publish_bytes(b"verified"))
    (store.objects / ref.removeprefix("sha256:")).write_bytes(b"tampered")
    async with client_for(store) as client:
        response = await client.get(f"/api/objects/{ref}")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "integrity_error"
    assert b"tampered" not in response.content


async def test_host_and_origin_guards(fixture: ReviewFixture) -> None:
    app = create_app(fixture.store)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        foreign = await client.get("/api/store", headers={"host": "evil.example"})
        cross_origin = await client.post(
            f"/api/verify/{fixture.manifest_ref}", headers={"origin": "https://evil.example"}
        )
        wrong_port = await client.post(
            f"/api/verify/{fixture.manifest_ref}", headers={"origin": "http://localhost:81"}
        )
        same_origin = await client.post(
            f"/api/verify/{fixture.manifest_ref}", headers={"origin": "http://localhost"}
        )
        cross_origin_refresh = await client.post(
            "/api/store/refresh", headers={"origin": "https://evil.example"}
        )
    assert foreign.status_code == 400
    assert foreign.json()["error"]["code"] == "invalid_host"
    assert cross_origin.status_code == 403
    assert cross_origin.json()["error"]["code"] == "cross_origin"
    assert wrong_port.status_code == 403
    assert same_origin.status_code == 200
    assert cross_origin_refresh.status_code == 403
    with pytest.raises(ValueError, match="requires --allow-remote"):
        validate_bind_host("192.0.2.10")
    validate_bind_host("192.0.2.10", allow_remote=True)
    with pytest.raises(ValueError, match="wildcard addresses"):
        validate_bind_host("0.0.0.0", allow_remote=True)


async def test_remote_bind_requires_its_configured_host(tmp_path: Path) -> None:
    app = create_app(ObjectStore(tmp_path / "remote"), host="review.example", allow_remote=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://review.example"
    ) as client:
        configured = await client.get("/api/store")
        loopback = await client.get("/api/store", headers={"host": "localhost"})
    assert configured.status_code == 200
    assert loopback.status_code == 400
    assert loopback.json()["error"]["code"] == "invalid_host"


def test_main_warns_for_remote_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[object, str, int]] = []

    def run(app: object, *, host: str, port: int) -> None:
        calls.append((app, host, port))

    monkeypatch.setattr("uvicorn.run", run)
    assert server.main([str(tmp_path / "store"), "--host", "review.example", "--allow-remote"]) == 0
    assert [(host, port) for _, host, port in calls] == [("review.example", 7557)]
    warning = capsys.readouterr().err
    assert "exposed remotely without authentication" in warning
    assert "requests must use 'review.example' in the Host header" in warning


async def test_application_shell_route(tmp_path: Path) -> None:
    async with client_for(ObjectStore(tmp_path / "shell")) as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert b'<main id="app"' in response.content


async def test_direct_corrupt_root_is_422(fixture: ReviewFixture, tmp_path: Path) -> None:
    source = fixture.studies.report_refs["scalar"]
    store = ObjectStore(tmp_path / "corrupt-root")
    for path in fixture.store.objects.iterdir():
        if path.is_file():
            store.objects.mkdir(parents=True, exist_ok=True)
            (store.objects / path.name).write_bytes(path.read_bytes())
    app = create_app(store)
    (store.objects / source.removeprefix("sha256:")).write_bytes(b"corrupt")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        response = await client.get(f"/api/reports/{source}")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "corrupt_root"
