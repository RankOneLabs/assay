"""Validation for model-visible, mount-free repository snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any
from unicodedata import category


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
            or any(category(character).startswith("C") for character in raw_path)
            or len(raw_path.encode("utf-8")) > 4_096
            or any(len(part.encode("utf-8")) > 255 for part in raw_parts)
        ):
            raise ValueError(f"unsafe repository path: {raw_path}")
        try:
            source_size = len(source.encode("utf-8"))
        except UnicodeEncodeError as error:
            raise ValueError(f"repository source is not valid UTF-8 text: {raw_path}") from error
        total += source_size
        if total > max_total_bytes:
            raise ValueError("repository exceeds the byte limit")
        repository[raw_path] = source
    paths = set(repository)
    for raw_path in paths:
        parts = raw_path.split("/")
        if any("/".join(parts[:index]) in paths for index in range(1, len(parts))):
            raise ValueError("repository path collides with a directory")
    return dict(sorted(repository.items()))
