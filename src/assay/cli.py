from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import cast

from assay.store import ObjectIntegrityError, ObjectStore
from assay.verify import export_bundle, verify_bundle

_REVIEW_SERVER_DEPENDENCIES = frozenset({"fastapi", "uvicorn"})


def _handle_verify(args: argparse.Namespace) -> int:
    failures = verify_bundle(ObjectStore(args.bundle), args.root_ref)
    for failure in failures:
        print(f"{failure.code}: {failure.message}")
    return 1 if failures else 0


def _handle_export(args: argparse.Namespace) -> int:
    try:
        export_bundle(ObjectStore(args.store), args.root_ref, args.destination)
    except (OSError, ValueError, ObjectIntegrityError) as exc:
        print(f"export_failed: {exc}")
        return 1
    return 0


def _review_import_failed(command: str, error: ImportError) -> int:
    missing = error.name.split(".", 1)[0] if error.name else None
    if missing in _REVIEW_SERVER_DEPENDENCIES:
        print(
            f"review_{command}_failed: install assay[review] to use the review server "
            f"(missing {error.name})"
        )
    else:
        print(f"review_{command}_failed: {error}")
    return 1


def _handle_review_serve(args: argparse.Namespace) -> int:
    try:
        from assay.review.server import main as serve_review

        arguments = [args.store, "--host", args.host, "--port", str(args.port)]
        if args.allow_remote:
            arguments.append("--allow-remote")
        return serve_review(arguments)
    except ImportError as error:
        return _review_import_failed("serve", error)


def _handle_review_export(args: argparse.Namespace) -> int:
    try:
        from assay.review.export import export_review

        export_review(ObjectStore(args.store), args.root_ref, args.output)
    except ImportError as error:
        return _review_import_failed("export", error)
    except (OSError, ValueError, ObjectIntegrityError) as error:
        print(f"review_export_failed: {error}")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="assay")
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("bundle")
    verify.add_argument("root_ref")
    verify.set_defaults(handler=_handle_verify)
    export = subparsers.add_parser("export")
    export.add_argument("store")
    export.add_argument("root_ref")
    export.add_argument("destination")
    export.set_defaults(handler=_handle_export)
    review = subparsers.add_parser("review")
    review_commands = review.add_subparsers(dest="review_command", required=True)
    review_serve = review_commands.add_parser("serve")
    review_serve.add_argument("store")
    review_serve.add_argument("--port", type=int, default=8765)
    review_serve.add_argument("--host", default="127.0.0.1")
    review_serve.add_argument("--allow-remote", action="store_true")
    review_serve.set_defaults(handler=_handle_review_serve)
    review_export = review_commands.add_parser("export")
    review_export.add_argument("store")
    review_export.add_argument("root_ref")
    review_export.add_argument("output")
    review_export.set_defaults(handler=_handle_review_export)
    args = parser.parse_args()
    handler = cast(Callable[[argparse.Namespace], int], args.handler)
    return handler(args)
