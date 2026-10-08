"""Typed, error-valued loaders for the committed study inputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from assay.code_metrics.api import CodeMetricsConfig
from assay.code_metrics.components import ComponentConfig

from .model import ComponentSpec, ImplementationRoot, ScopeSpec, SnapshotSpec


@dataclass(frozen=True, slots=True)
class ConfigError:
    file: str
    key: str
    detail: str


@dataclass(frozen=True, slots=True)
class Ok[T]:
    value: T


@dataclass(frozen=True, slots=True)
class Err[E]:
    error: E


type Result[T, E] = Ok[T] | Err[E]


def _read(path: Path) -> Ok[object] | Err[ConfigError]:
    try:
        return Ok(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError) as exc:
        return Err(ConfigError(str(path), "$", str(exc)))


def _mapping(value: object, path: Path, key: str) -> Ok[dict[str, object]] | Err[ConfigError]:
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
        return Err(ConfigError(str(path), key, "must be a mapping with string keys"))
    return Ok(value)


def _strings(value: object, path: Path, key: str) -> Ok[tuple[str, ...]] | Err[ConfigError]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        return Err(ConfigError(str(path), key, "must be a list of nonempty strings"))
    return Ok(tuple(value))


def _text(value: object, path: Path, key: str) -> Ok[str] | Err[ConfigError]:
    if not isinstance(value, str) or not value:
        return Err(ConfigError(str(path), key, "must be a nonempty string"))
    return Ok(value)


def load_snapshots(path: Path | None = None) -> Ok[tuple[SnapshotSpec, ...]] | Err[ConfigError]:
    path = path or Path(__file__).with_name("snapshots.yaml")
    raw = _read(path)
    if isinstance(raw, Err):
        return raw
    root = _mapping(raw.value, path, "$")
    if isinstance(root, Err):
        return root
    entries = root.value.get("snapshots")
    if not isinstance(entries, list) or not entries:
        return Err(ConfigError(str(path), "snapshots", "must be a nonempty list"))
    snapshots: list[SnapshotSpec] = []
    for i, item in enumerate(entries):
        key = f"snapshots[{i}]"
        row = _mapping(item, path, key)
        if isinstance(row, Err):
            return row
        fields: dict[str, str] = {}
        for field in ("id", "sha", "event", "selection_reason"):
            parsed = _text(row.value.get(field), path, f"{key}.{field}")
            if isinstance(parsed, Err):
                return parsed
            fields[field] = parsed.value
        raw_date = row.value.get("date")
        if raw_date is not None and not isinstance(raw_date, date):
            return Err(ConfigError(str(path), f"{key}.date", "must be a YAML date or null"))
        number = row.value.get("pr_number")
        if number is not None and (type(number) is not int or number < 1):
            return Err(ConfigError(
                str(path), f"{key}.pr_number", "must be a positive integer or null"
            ))
        provisional = row.value.get("provisional", False)
        if type(provisional) is not bool:
            return Err(ConfigError(str(path), f"{key}.provisional", "must be a boolean"))
        final_sha = row.value.get("final_sha")
        if final_sha is not None and not isinstance(final_sha, str):
            return Err(ConfigError(str(path), f"{key}.final_sha", "must be a string or null"))
        snapshots.append(SnapshotSpec(**fields, date=raw_date, pr_number=number,
                                      provisional=provisional, final_sha=final_sha))
    if len({item.id for item in snapshots}) != len(snapshots):
        return Err(ConfigError(str(path), "snapshots", "ids must be unique"))
    return Ok(tuple(snapshots))


def load_scope(path: Path | None = None) -> Ok[ScopeSpec] | Err[ConfigError]:
    path = path or Path(__file__).with_name("scope.yaml")
    raw = _read(path)
    if isinstance(raw, Err):
        return raw
    root = _mapping(raw.value, path, "$")
    if isinstance(root, Err):
        return root
    includes = _strings(root.value.get("include_paths"), path, "include_paths")
    excludes = _strings(root.value.get("exclude_globs"), path, "exclude_globs")
    if isinstance(includes, Err):
        return includes
    if isinstance(excludes, Err):
        return excludes
    entries = root.value.get("implementation_roots")
    if not isinstance(entries, list) or not entries:
        return Err(ConfigError(str(path), "implementation_roots", "must be a nonempty list"))
    roots: list[ImplementationRoot] = []
    for i, item in enumerate(entries):
        key = f"implementation_roots[{i}]"
        row = _mapping(item, path, key)
        if isinstance(row, Err):
            return row
        fields: dict[str, str] = {}
        for field in ("prefix", "implementation", "include_path"):
            parsed = _text(row.value.get(field), path, f"{key}.{field}")
            if isinstance(parsed, Err):
                return parsed
            fields[field] = parsed.value
        post = row.value.get("post_rewrite_only", False)
        if type(post) is not bool:
            return Err(ConfigError(str(path), f"{key}.post_rewrite_only", "must be a boolean"))
        if fields["include_path"] not in includes.value:
            return Err(ConfigError(str(path), f"{key}.include_path", "must name an include path"))
        roots.append(ImplementationRoot(**fields, post_rewrite_only=post))
    return Ok(ScopeSpec(includes.value, excludes.value, tuple(roots)))


def load_components(path: Path | None = None) -> Ok[tuple[ComponentSpec, ...]] | Err[ConfigError]:
    path = path or Path(__file__).with_name("code-metrics.yaml")
    raw = _read(path)
    if isinstance(raw, Err):
        return raw
    root = _mapping(raw.value, path, "$")
    if isinstance(root, Err):
        return root
    allowed = {
        "clone_min_lines", "clone_min_tokens", "ruff_ignore", "components",
        "allow_unmatched_patterns",
    }
    if set(root.value) - allowed:
        return Err(ConfigError(str(path), "$", "unknown config key"))
    entries = root.value.get("components")
    if not isinstance(entries, list) or not entries:
        return Err(ConfigError(str(path), "components", "must be a nonempty list"))
    components: list[ComponentSpec] = []
    for i, item in enumerate(entries):
        key = f"components[{i}]"
        row = _mapping(item, path, key)
        if isinstance(row, Err):
            return row
        if set(row.value) != {"name", "patterns"}:
            return Err(ConfigError(str(path), key, "requires only name and patterns"))
        name = _text(row.value["name"], path, f"{key}.name")
        patterns = _strings(row.value["patterns"], path, f"{key}.patterns")
        if isinstance(name, Err):
            return name
        if isinstance(patterns, Err):
            return patterns
        components.append(ComponentSpec(name.value, patterns.value))
    if len({c.name for c in components}) != len(components):
        return Err(ConfigError(str(path), "components", "names must be unique"))
    return Ok(tuple(components))


def load_code_metrics_config(path: Path | None = None) -> Ok[CodeMetricsConfig] | Err[ConfigError]:
    path = path or Path(__file__).with_name("code-metrics.yaml")
    components = load_components(path)
    if isinstance(components, Err):
        return components
    raw = _read(path)
    if isinstance(raw, Err):
        return raw
    root = _mapping(raw.value, path, "$")
    if isinstance(root, Err):
        return root
    thresholds: dict[str, int] = {}
    for key in ("clone_min_lines", "clone_min_tokens"):
        value = root.value.get(key, 5 if key == "clone_min_lines" else 50)
        if type(value) is not int or value < 1:
            return Err(ConfigError(str(path), key, "must be a positive integer"))
        thresholds[key] = value
    ignored = root.value.get("ruff_ignore", [])
    ignored_result = _strings(ignored, path, "ruff_ignore")
    if isinstance(ignored_result, Err):
        return ignored_result
    allow = root.value.get("allow_unmatched_patterns", False)
    if type(allow) is not bool:
        return Err(ConfigError(str(path), "allow_unmatched_patterns", "must be a boolean"))
    return Ok(CodeMetricsConfig(
        clone_min_lines=thresholds["clone_min_lines"],
        clone_min_tokens=thresholds["clone_min_tokens"],
        ruff_ignore=ignored_result.value,
        components=tuple(ComponentConfig(c.name, c.patterns) for c in components.value),
        allow_unmatched_patterns=allow,
    ))
