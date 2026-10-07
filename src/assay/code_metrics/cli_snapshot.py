"""Turn a directory into the snapshot mapping accepted by the metrics API."""

from __future__ import annotations

import os
from fnmatch import fnmatchcase
from pathlib import Path

from pydantic import TypeAdapter

from .models import RepoPath, Snapshot

_EXCLUDE_PATH = TypeAdapter(RepoPath)

DEFAULT_EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".assay",
        ".claude",
        "dist",
        "build",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    }
)


def snapshot_directory(
    path: str | Path, *, exclude: tuple[str, ...] = ()
) -> tuple[Snapshot, tuple[str, ...]]:
    """Read Python files under *path*, pruning named directories and globs."""
    root = Path(path)
    if not root.is_dir():
        raise ValueError(f"{root} is not a directory")
    for pattern in exclude:
        try:
            _EXCLUDE_PATH.validate_python(pattern)
        except ValueError as error:
            raise ValueError(f"invalid exclude glob {pattern!r}: {error}") from error
    resolved = tuple(sorted(DEFAULT_EXCLUDED_DIRECTORIES | set(exclude)))
    files: dict[str, str] = {}
    for directory, directories, filenames in os.walk(
        root, followlinks=False, onerror=_raise_walk_error
    ):
        relative = Path(directory).relative_to(root)
        directories[:] = sorted(
            name
            for name in directories
            if not _excluded((relative / name).as_posix(), name, resolved)
        )
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            key = (relative / name).as_posix()
            if not _excluded(key, name, exclude):
                files[key] = (Path(directory) / name).read_text(encoding="utf-8")
    return files, resolved


def _raise_walk_error(error: OSError) -> None:
    raise error


def _excluded(path: str, name: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatchcase(path, pattern) or fnmatchcase(name, pattern) for pattern in patterns)
