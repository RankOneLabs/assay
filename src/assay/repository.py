"""Validation for model-visible, mount-free repository snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any


def validate_repository(
    value: Any,
    *,
    max_files: int = 200,
    max_total_bytes: int = 1_000_000,
) -> dict[str, str]:
    """Return a sorted copy after enforcing a portable relative-file boundary."""
    if not isinstance(value, Mapping) or not value:
        raise ValueError("repository must be a nonempty path-to-source object")
    if len(value) > max_files:
        raise ValueError("repository has too many files")
    repository: dict[str, str] = {}
    total = 0
    for raw_path, source in value.items():
        if not isinstance(raw_path, str) or not isinstance(source, str):
            raise ValueError("repository paths and contents must be strings")
        path = PurePosixPath(raw_path)
        raw_parts = raw_path.split("/")
        if (
            not raw_path
            or "\\" in raw_path
            or path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in raw_parts)
        ):
            raise ValueError(f"unsafe repository path: {raw_path}")
        total += len(source.encode("utf-8"))
        if total > max_total_bytes:
            raise ValueError("repository exceeds the byte limit")
        repository[raw_path] = source
    return dict(sorted(repository.items()))
