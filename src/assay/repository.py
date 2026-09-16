"""Validation for model-visible, mount-free repository snapshots."""

from __future__ import annotations

import os
import unicodedata
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
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
    normalized_seen: dict[str, str] = {}
    for raw_path in paths:
        normalized = unicodedata.normalize("NFC", raw_path).casefold()
        if normalized in normalized_seen and normalized_seen[normalized] != raw_path:
            raise ValueError(
                f"duplicate repository path under case/unicode folding: {raw_path!r} "
                f"collides with {normalized_seen[normalized]!r}"
            )
        normalized_seen[normalized] = raw_path
    return dict(sorted(repository.items()))


def validate_source_tree(
    root: Path,
    *,
    max_files: int = 200,
    max_total_bytes: int = 1_000_000,
) -> dict[str, str]:
    """Read an on-disk realization directory into a validated repository mapping.

    This is the sole boundary between a realization directory and a
    model-visible repository payload: it never reads a symlink or a special
    file (fifo, socket, device), and every regular file must decode as
    UTF-8. Packaging must call this instead of pointing a Docker build
    context or a Trial mount directly at ``root``.
    """
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"realization root is not a plain directory: {root}")

    def _raise_walk_error(error: OSError) -> None:
        raise ValueError(f"could not read realization directory: {error}") from error

    files: dict[str, str] = {}
    total_bytes = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=_raise_walk_error):
        dirnames.sort()
        for name in dirnames:
            if (Path(dirpath) / name).is_symlink():
                raise ValueError(f"symlink directory is not allowed in a realization: {name}")
        for name in sorted(filenames):
            if len(files) >= max_files:
                raise ValueError("repository has too many files")
            full = Path(dirpath) / name
            rel = full.relative_to(root).as_posix()
            if full.is_symlink():
                raise ValueError(f"symlink is not allowed in a realization: {rel}")
            if not full.is_file():
                raise ValueError(f"special file is not allowed in a realization: {rel}")
            total_bytes += full.stat().st_size
            if total_bytes > max_total_bytes:
                raise ValueError("repository exceeds the byte limit")
            try:
                files[rel] = full.read_text(encoding="utf-8")
            except UnicodeDecodeError as error:
                raise ValueError(f"realization file is not valid UTF-8 text: {rel}") from error
    return validate_repository(files, max_files=max_files, max_total_bytes=max_total_bytes)
