"""Versioned inputs and report metadata for the Oakridge history study."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class SnapshotSpec:
    id: str
    sha: str
    date: date | None
    pr_number: int | None
    event: str
    selection_reason: str
    provisional: bool = False


@dataclass(frozen=True, slots=True)
class ImplementationRoot:
    prefix: str
    implementation: str
    include_path: str
    post_rewrite_only: bool = False


@dataclass(frozen=True, slots=True)
class ScopeSpec:
    include_paths: tuple[str, ...]
    exclude_globs: tuple[str, ...]
    implementation_roots: tuple[ImplementationRoot, ...]


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    name: str
    patterns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SnapshotMetadata:
    snapshot: SnapshotSpec
    resolved_include_paths: tuple[str, ...]
