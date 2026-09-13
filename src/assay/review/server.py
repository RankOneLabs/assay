"""Loopback HTTP adapter for the verified review reading layer."""

from __future__ import annotations

import argparse
import ipaddress
import re
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from assay.review.index import ReviewIndex, build_index
from assay.review.model import canonical_view_json
from assay.review.read import (
    PairPlanUnavailable,
    PairSelectionError,
    ReadError,
    ReviewReader,
    verify,
)
from assay.store import ObjectIntegrityError, ObjectStore

OBJECT_LIMIT = 8 * 1024 * 1024
TRUNCATION_MARKER = b"\n\n[object truncated at 8 MiB]\n"
_REF = re.compile(r"sha256:[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_CELL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*:[A-Za-z0-9][A-Za-z0-9_.-]*:w[0-9]+\Z")
_LOOSE_RUN = re.compile(r"unmanifested:([A-Za-z0-9][A-Za-z0-9_.-]*):(sha256:[0-9a-f]{64})\Z")
_STATIC = Path(__file__).with_name("static")


def json_response(value: object, status_code: int = 200) -> Response:
    """Return a view encoded by the same canonical encoder as static exports."""
    return Response(
        content=canonical_view_json(value), status_code=status_code, media_type="application/json"
    )


def _error(status: int, code: str, message: str, ref: str | None = None) -> Response:
    return json_response({"error": {"code": code, "message": message, "ref": ref}}, status)


def _validate_ref(value: str, label: str = "object reference") -> None:
    if _REF.fullmatch(value) is None:
        raise HTTPException(400, detail=("malformed_ref", f"malformed {label}", value))


def _validate_identifier(value: str, label: str) -> None:
    if _IDENTIFIER.fullmatch(value) is None:
        raise HTTPException(400, detail=("malformed_identifier", f"malformed {label}", value))


def _validate_run_key(run_key: str) -> None:
    if _REF.fullmatch(run_key) is not None:
        return
    match = _LOOSE_RUN.fullmatch(run_key)
    if match is None:
        raise HTTPException(400, detail=("malformed_run_key", "malformed run key", run_key))
    _validate_identifier(match[1], "run id")
    _validate_ref(match[2], "plan reference")


def _hostname(value: str) -> str:
    """Extract and normalize a Host header without accepting userinfo or paths."""
    try:
        parsed = urlsplit("//" + value)
        if parsed.username is not None or parsed.password is not None or parsed.path:
            return ""
        return (parsed.hostname or "").rstrip(".").lower()
    except ValueError:
        return ""


def _is_loopback_name(host: str) -> bool:
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_bind_host(host: str, *, allow_remote: bool = False) -> None:
    """Reject accidental unauthenticated remote binding."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and address.is_unspecified:
        raise ValueError(
            "--host must be a reachable hostname or IP; "
            "wildcard addresses cannot pass Host validation"
        )
    if not _is_loopback_name(host) and not allow_remote:
        raise ValueError("non-loopback --host requires --allow-remote")


def _known_run(index: ReviewIndex, run_key: str) -> bool:
    return any(item.run_key == run_key for item in index.runs)


def _root_exists_and_verifies(store: ObjectStore, ref: str) -> None:
    try:
        store.read_bytes(ref)
    except FileNotFoundError:
        raise HTTPException(
            404, detail=("not_found", "requested root was not found", ref)
        ) from None
    except ObjectIntegrityError:
        raise HTTPException(
            422, detail=("corrupt_root", "requested root failed its digest check", ref)
        ) from None
    except OSError:
        raise HTTPException(
            422, detail=("corrupt_root", "requested root is unreadable", ref)
        ) from None


def _textual(data: bytes) -> bool:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return all(character in "\t\n\r" or ord(character) >= 32 for character in text)


def create_app(
    store: ObjectStore | Path | str,
    *,
    host: str = "127.0.0.1",
    allow_remote: bool = False,
) -> FastAPI:
    """Create the review application for one object store."""
    validate_bind_host(host, allow_remote=allow_remote)
    object_store = store if isinstance(store, ObjectStore) else ObjectStore(store)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = object_store
    app.state.index = build_index(object_store)
    allowed_hosts = {"localhost", "127.0.0.1", "::1", host.rstrip(".").lower()}

    @app.middleware("http")
    async def request_guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_host = _hostname(request.headers.get("host", ""))
        if not (_is_loopback_name(request_host) or request_host in allowed_hosts):
            return _error(400, "invalid_host", "request Host is not allowed")
        if request.method == "POST":
            origin = request.headers.get("origin")
            if origin:
                origin_scheme = ""
                try:
                    parsed_origin = urlsplit(origin)
                    origin_scheme = parsed_origin.scheme
                    origin_host = _hostname(parsed_origin.netloc)
                    origin_port = parsed_origin.port or (
                        443 if parsed_origin.scheme == "https" else 80
                    )
                    request_port = request.url.port or (
                        443 if request.url.scheme == "https" else 80
                    )
                except ValueError:
                    origin_host = ""
                    origin_port = -1
                    request_port = -2
                if (
                    origin_scheme not in {"http", "https"}
                    or origin_scheme != request.url.scheme
                    or origin_host != request_host
                    or origin_port != request_port
                ):
                    return _error(403, "cross_origin", "action requests must be same-origin")
        return await call_next(request)

    # Keep this first: clients use it to discover every other view.
    @app.get("/api/store")
    async def get_store(refresh: bool = False) -> Response:
        if refresh:
            app.state.index = build_index(object_store, refresh=True)
        return json_response(ReviewReader(object_store, app.state.index).store_summary())

    @app.get("/api/runs/{run_key}")
    async def get_run(run_key: str) -> Response:
        _validate_run_key(run_key)
        if not _known_run(app.state.index, run_key):
            if _REF.fullmatch(run_key):
                try:
                    object_store.read_bytes(run_key)
                except ObjectIntegrityError:
                    raise HTTPException(
                        422,
                        detail=("corrupt_root", "requested root failed its digest check", run_key),
                    ) from None
                except (FileNotFoundError, OSError):
                    pass
            raise HTTPException(404, detail=("not_found", "run was not found", run_key))
        try:
            return json_response(ReviewReader(object_store, app.state.index).run(run_key))
        except ReadError as error:
            raise HTTPException(422, detail=("corrupt_root", str(error), run_key)) from None

    @app.get("/api/runs/{run_key}/cells/{cell_id}")
    async def get_cell(run_key: str, cell_id: str) -> Response:
        _validate_run_key(run_key)
        if _CELL.fullmatch(cell_id) is None:
            raise HTTPException(400, detail=("malformed_coordinate", "malformed cell id", cell_id))
        if not _known_run(app.state.index, run_key):
            raise HTTPException(404, detail=("not_found", "run was not found", run_key))
        try:
            return json_response(ReviewReader(object_store, app.state.index).cell(run_key, cell_id))
        except KeyError:
            raise HTTPException(404, detail=("not_found", "cell was not found", cell_id)) from None
        except ReadError as error:
            raise HTTPException(422, detail=("corrupt_root", str(error), run_key)) from None

    @app.get("/api/runs/{run_key}/pairs/{subject_id}")
    async def get_pair(
        run_key: str,
        subject_id: str,
        reference: str | None = None,
        candidate: str | None = None,
    ) -> Response:
        _validate_run_key(run_key)
        _validate_identifier(subject_id, "subject id")
        if reference is not None:
            _validate_identifier(reference, "reference arm")
        if candidate is not None:
            _validate_identifier(candidate, "candidate arm")
        if not _known_run(app.state.index, run_key):
            raise HTTPException(404, detail=("not_found", "run was not found", run_key))
        reader = ReviewReader(object_store, app.state.index)
        try:
            return json_response(reader.pair(run_key, subject_id, reference, candidate))
        except PairPlanUnavailable as error:
            raise HTTPException(
                409, detail=("plan_unavailable", str(error), error.plan_ref)
            ) from None
        except PairSelectionError as error:
            raise HTTPException(400, detail=(error.code, str(error), error.value)) from None
        except ReadError as error:
            raise HTTPException(422, detail=("corrupt_root", str(error), run_key)) from None

    @app.get("/api/runs/{run_key}/ambiguous")
    async def get_run_ambiguities(run_key: str) -> Response:
        _validate_run_key(run_key)
        if not _known_run(app.state.index, run_key):
            raise HTTPException(404, detail=("not_found", "run was not found", run_key))
        return json_response(ReviewReader(object_store, app.state.index).ambiguities(run_key))

    @app.get("/api/reports")
    async def get_reports() -> Response:
        return json_response(ReviewReader(object_store, app.state.index).store_summary().reports)

    @app.get("/api/reports/{report_ref}")
    async def get_report(report_ref: str) -> Response:
        _validate_ref(report_ref, "report reference")
        _root_exists_and_verifies(object_store, report_ref)
        if not any(item.report_ref == report_ref for item in app.state.index.reports):
            raise HTTPException(404, detail=("not_found", "report was not found", report_ref))
        try:
            return json_response(ReviewReader(object_store, app.state.index).report(report_ref))
        except ReadError as error:
            raise HTTPException(422, detail=("corrupt_root", str(error), report_ref)) from None

    @app.post("/api/reports/{report_ref}/recompute")
    async def post_recompute(report_ref: str) -> Response:
        _validate_ref(report_ref, "report reference")
        _root_exists_and_verifies(object_store, report_ref)
        if not any(item.report_ref == report_ref for item in app.state.index.reports):
            raise HTTPException(404, detail=("not_found", "report was not found", report_ref))
        try:
            return json_response(ReviewReader(object_store, app.state.index).recompute(report_ref))
        except ReadError as error:
            raise HTTPException(422, detail=("corrupt_root", str(error), report_ref)) from None

    @app.get("/api/reports/{report_ref}/recompute", include_in_schema=False)
    async def get_recompute_not_allowed(report_ref: str) -> Response:
        del report_ref
        return _error(405, "method_not_allowed", "recompute requires POST")

    @app.post("/api/verify/{root_ref}")
    async def post_verify(root_ref: str, scope: str = "root") -> Response:
        _validate_ref(root_ref, "root reference")
        if scope not in {"root", "bundle"}:
            raise HTTPException(
                400, detail=("invalid_scope", "scope must be root or bundle", root_ref)
            )
        _root_exists_and_verifies(object_store, root_ref)
        return json_response(verify(object_store, root_ref, scope))  # type: ignore[arg-type]

    @app.get("/api/verify/{root_ref}", include_in_schema=False)
    async def get_verify_not_allowed(root_ref: str) -> Response:
        del root_ref
        return _error(405, "method_not_allowed", "verification requires POST")

    @app.get("/api/objects/{ref}")
    async def get_object(ref: str) -> Response:
        _validate_ref(ref)
        try:
            data = object_store.read_bytes(ref)
        except FileNotFoundError:
            raise HTTPException(404, detail=("not_found", "object was not found", ref)) from None
        except ObjectIntegrityError:
            raise HTTPException(
                422, detail=("integrity_error", "object failed its digest check", ref)
            ) from None
        except OSError:
            raise HTTPException(
                422, detail=("unreadable_object", "object is unreadable", ref)
            ) from None
        textual = _textual(data)
        headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Assay-Object-Size": str(len(data)),
            "X-Assay-Truncated": "false",
        }
        if not textual:
            headers["Content-Disposition"] = (
                f'attachment; filename="{ref.removeprefix("sha256:")}.bin"'
            )
            if len(data) > OBJECT_LIMIT:
                response = _error(
                    413, "object_too_large", "binary object exceeds the 8 MiB limit", ref
                )
                response.headers.update(headers)
                return response
        elif len(data) > OBJECT_LIMIT:
            data = data[: OBJECT_LIMIT - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER
            headers["X-Assay-Truncated"] = "true"
        return Response(content=data, media_type="text/plain", headers=headers)

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, error: HTTPException) -> Response:
        if isinstance(error.detail, tuple) and len(error.detail) == 3:
            code, message, ref = error.detail
            return _error(error.status_code, str(code), str(message), ref)
        code = "not_found" if error.status_code == 404 else "http_error"
        return _error(error.status_code, code, str(error.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _error_value: RequestValidationError) -> Response:
        return _error(400, "malformed_request", "request parameters are malformed")

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def unknown_api(path: str) -> Response:
        del path
        return _error(404, "not_found", "API route was not found")

    @app.get("/")
    async def application_shell() -> FileResponse:
        return FileResponse(_STATIC / "index.html", media_type="text/html")

    app.mount("/", StaticFiles(directory=_STATIC), name="review-static")
    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m assay.review.server")
    parser.add_argument("store")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="reachable bind hostname or IP (wildcard addresses are rejected)",
    )
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--allow-remote", action="store_true")
    args = parser.parse_args(argv)
    try:
        validate_bind_host(args.host, allow_remote=args.allow_remote)
    except ValueError as error:
        parser.error(str(error))
    if not _is_loopback_name(args.host):
        print(
            f"WARNING: review server is exposed remotely without authentication; "
            f"requests must use {args.host!r} in the Host header",
            file=sys.stderr,
        )
    import uvicorn

    uvicorn.run(
        create_app(args.store, host=args.host, allow_remote=args.allow_remote),
        host=args.host,
        port=args.port,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
