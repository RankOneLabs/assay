from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import Any, cast

import yaml

from assay.store import ObjectIntegrityError, ObjectStore
from assay.verify import export_bundle, verify_bundle

_REVIEW_SERVER_DEPENDENCIES = frozenset({"fastapi", "uvicorn"})
_CODE_METRICS_DEPENDENCIES = frozenset(
    {"grimp", "radon", "complexipy", "lizard", "ruff", "mypy", "tree_sitter", "tree_sitter_rust"}
)


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
        from assay.review.server import validate_bind_host

        import_module("uvicorn")
    except ImportError as error:
        return _review_import_failed("serve", error)
    try:
        validate_bind_host(args.host, allow_remote=args.allow_remote)
    except ValueError as error:
        args.parser.error(str(error))
    arguments = [args.store, "--host", args.host, "--port", str(args.port)]
    if args.allow_remote:
        arguments.append("--allow-remote")
    return serve_review(arguments)


def _handle_review_export(args: argparse.Namespace) -> int:
    try:
        from assay.review.export import export_review

    except ImportError as error:
        return _review_import_failed("export", error)
    try:
        export_review(ObjectStore(args.store), args.root_ref, args.output)
    except (OSError, ValueError, ObjectIntegrityError) as error:
        print(f"review_export_failed: {error}")
        return 1
    return 0


def _code_metrics_import_failed(command: str, error: ImportError) -> int:
    missing = error.name.split(".", 1)[0] if error.name else None
    if missing in _CODE_METRICS_DEPENDENCIES:
        print(
            f"code_metrics_{command}_failed: install assay[code-metrics] to measure "
            f"code metrics (missing {error.name})"
        )
    else:
        print(f"code_metrics_{command}_failed: {error}")
    return 1


def _code_metrics_config(path: str | None) -> Any:
    from assay.code_metrics.api import CodeMetricsConfig
    from assay.code_metrics.components import ComponentConfig
    from assay.code_metrics.errors import ConfigurationError

    if path is None:
        return CodeMetricsConfig()
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ConfigurationError(str(error)) from error
    if not isinstance(raw, dict):
        raise ConfigurationError("config must be an object")
    if not all(isinstance(key, str) for key in raw):
        raise ConfigurationError("config keys must be strings")
    allowed = {
        "clone_min_lines",
        "clone_min_tokens",
        "ruff_ignore",
        "components",
        "allow_unmatched_patterns",
    }
    if set(raw) - allowed:
        raise ConfigurationError(f"unknown config keys: {sorted(set(raw) - allowed)}")
    values: dict[str, Any] = {
        "clone_min_lines": 5,
        "clone_min_tokens": 50,
        "ruff_ignore": (),
        "components": (),
        "allow_unmatched_patterns": False,
    }
    values.update(raw)
    for key in ("clone_min_lines", "clone_min_tokens"):
        if type(values[key]) is not int or values[key] < 1:
            raise ConfigurationError(f"{key} must be a positive integer")
    if not isinstance(values["ruff_ignore"], list) and values["ruff_ignore"] != ():
        raise ConfigurationError("ruff_ignore must be a list of strings")
    if not all(isinstance(item, str) for item in values["ruff_ignore"]):
        raise ConfigurationError("ruff_ignore must be a list of strings")
    if type(values["allow_unmatched_patterns"]) is not bool:
        raise ConfigurationError("allow_unmatched_patterns must be a bool")
    if not isinstance(values["components"], list) and values["components"] != ():
        raise ConfigurationError("components must be a list")
    components = []
    for item in values["components"]:
        if not isinstance(item, dict) or set(item) != {"name", "patterns"}:
            raise ConfigurationError("each component needs name and patterns")
        if not isinstance(item["name"], str) or not isinstance(item["patterns"], list):
            raise ConfigurationError("component name must be a string and patterns a list")
        if not all(isinstance(pattern, str) for pattern in item["patterns"]):
            raise ConfigurationError("component patterns must be strings")
        components.append(ComponentConfig(item["name"], tuple(item["patterns"])))
    return CodeMetricsConfig(
        clone_min_lines=values["clone_min_lines"],
        clone_min_tokens=values["clone_min_tokens"],
        ruff_ignore=tuple(values["ruff_ignore"]),
        components=tuple(components),
        allow_unmatched_patterns=values["allow_unmatched_patterns"],
    )


def _with_exclusions(report: Any, excluded: tuple[str, ...]) -> Any:
    configuration = type(report.configuration).model_validate(
        {**report.configuration.model_dump(), "excluded_directories": excluded}
    )
    return report.model_copy(update={"configuration": configuration})


def _write_canonical(model: Any) -> None:
    from assay.canonical import canonical_json

    sys.stdout.buffer.write(canonical_json(model.model_dump(mode="json")))
    sys.stdout.buffer.flush()


def _handle_code_metrics_snapshot(args: argparse.Namespace) -> int:
    try:
        from assay.code_metrics import analyze
        from assay.code_metrics.cli_snapshot import snapshot_directory

        for dependency in sorted(_CODE_METRICS_DEPENDENCIES):
            import_module(dependency)
    except ImportError as error:
        return _code_metrics_import_failed("snapshot", error)
    try:
        snapshot, excluded = snapshot_directory(args.path, exclude=tuple(args.exclude))
        report = _with_exclusions(
            analyze(snapshot, config=_code_metrics_config(args.config)), excluded
        )
        _write_canonical(report)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"code_metrics_snapshot_failed: {error}")
        return 1
    return 0


def _handle_code_metrics_compare(args: argparse.Namespace) -> int:
    try:
        from assay.code_metrics import compare
        from assay.code_metrics.cli_snapshot import snapshot_directory

        for dependency in sorted(_CODE_METRICS_DEPENDENCIES):
            import_module(dependency)
    except ImportError as error:
        return _code_metrics_import_failed("compare", error)
    try:
        before, before_excluded = snapshot_directory(args.before_path, exclude=tuple(args.exclude))
        after, after_excluded = snapshot_directory(args.after_path, exclude=tuple(args.exclude))
        result = compare(before, after, config=_code_metrics_config(args.config))
        result = result.model_copy(
            update={
                "before": _with_exclusions(result.before, before_excluded),
                "after": _with_exclusions(result.after, after_excluded),
            }
        )
        _write_canonical(result)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"code_metrics_compare_failed: {error}")
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
    review_serve.add_argument("--port", type=int, default=7557)
    review_serve.add_argument("--host", default="127.0.0.1")
    review_serve.add_argument("--allow-remote", action="store_true")
    review_serve.set_defaults(handler=_handle_review_serve, parser=review_serve)
    review_export = review_commands.add_parser("export")
    review_export.add_argument("store")
    review_export.add_argument("root_ref")
    review_export.add_argument("output")
    review_export.set_defaults(handler=_handle_review_export)
    code_metrics = subparsers.add_parser("code-metrics")
    metrics_commands = code_metrics.add_subparsers(dest="metrics_command", required=True)
    snapshot = metrics_commands.add_parser("snapshot")
    snapshot.add_argument("path", metavar="PATH")
    comparison = metrics_commands.add_parser("compare")
    comparison.add_argument("before_path", metavar="BEFORE_PATH")
    comparison.add_argument("after_path", metavar="AFTER_PATH")
    for command in (snapshot, comparison):
        command.add_argument("--config", metavar="FILE")
        command.add_argument("--exclude", metavar="GLOB", action="append", default=[])
        command.add_argument("--json", action="store_true")
    snapshot.set_defaults(handler=_handle_code_metrics_snapshot)
    comparison.set_defaults(handler=_handle_code_metrics_compare)
    args = parser.parse_args()
    handler = cast(Callable[[argparse.Namespace], int], args.handler)
    return handler(args)
