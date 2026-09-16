"""Path safety shared by every writer that materializes a package/repository
mapping onto a real directory (``pier_adapter.write_task_directory`` and
``container._materialize``).

Deliberately local rather than imported from ``assay.repository``: this
bridge project has no dependency edge back onto ``assay`` (see README.md).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path, PurePosixPath


def safe_relative_path(raw_path: str) -> PurePosixPath:
    """Reject anything that is not a plain, traversal-free relative path."""
    path = PurePosixPath(raw_path)
    if (
        not raw_path
        or "\\" in raw_path
        or path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"unsafe path: {raw_path}")
    return path


def materialize_under(root: Path, files: Mapping[str, str]) -> None:
    """Write ``files`` (relative path -> text content) under ``root``.

    Every path is checked against ``safe_relative_path`` before it is
    joined, so an absolute path or a ``..`` segment can never write outside
    ``root``.
    """
    for raw_path, content in files.items():
        rel = safe_relative_path(raw_path)
        full = root / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")


__all__ = ["materialize_under", "safe_relative_path"]
