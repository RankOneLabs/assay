"""Filesystem boundary shared by every handle that materializes a package
onto a real directory (``pier_adapter.write_task_directory`` and
``container._materialize``) or reads a trial's output back off one
(``collect_artifacts``).

Deliberately local rather than imported from ``assay.repository``: this
bridge project has no dependency edge back onto ``assay`` (see README.md).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path, PurePosixPath


def safe_relative_path(raw_path: str) -> PurePosixPath:
    """Reject anything that is not a canonical, traversal-free relative path.

    Materialization joins the parsed ``PurePosixPath`` to a real directory,
    so accepting two spellings that parse to the same path (for example
    ``instruction.md`` and ``./instruction.md``) would make a caller's path
    mapping non-injective. Require the wire spelling to already be canonical
    rather than silently choosing which entry wins on disk.
    """
    path = PurePosixPath(raw_path)
    if (
        not raw_path
        or "\\" in raw_path
        or path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != raw_path
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


def collect_artifacts(
    root: Path,
    *,
    max_bytes: int,
    max_aggregate_bytes: int,
    max_entries: int,
    aggregate_exempt_path: str,
) -> dict[str, bytes]:
    """Read every regular file under ``root`` into a path -> bytes mapping.

    The trial's own output is the least trustworthy directory this project
    reads: a model with write access to /submission can plant a symlink, a
    fifo, or a file larger than any manifest would ever declare. Only
    regular files are read, symlinks are skipped at every level rather than
    followed, and a file whose size exceeds ``max_bytes`` raises instead of
    being read -- the size is checked via ``lstat`` before any content is
    pulled into memory, so an oversized artifact never costs its own size.

    Paths are returned relative to ``root``, POSIX-style and sorted, so two
    runs over identical content produce identical mappings.
    """
    paths: list[Path] = []
    for path in root.rglob("*"):
        paths.append(path)
        if len(paths) > max_entries:
            raise ValueError("trial submission exceeds the filesystem entry limit")

    artifacts: dict[str, bytes] = {}
    aggregate_bytes = 0
    for path in sorted(paths):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if path.lstat().st_size > max_bytes:
            raise ValueError(f"trial artifact exceeds the byte limit: {relative}")
        safe_relative_path(relative)
        remaining = (
            max_bytes
            if relative == aggregate_exempt_path
            else min(max_bytes, max_aggregate_bytes - aggregate_bytes)
        )
        with path.open("rb") as artifact_file:
            data = artifact_file.read(remaining + 1)
        if len(data) > remaining:
            if relative == aggregate_exempt_path or remaining == max_bytes:
                raise ValueError(f"trial artifact exceeds the byte limit: {relative}")
            raise ValueError("trial artifacts exceed the aggregate byte limit")
        artifacts[relative] = data
        if relative != aggregate_exempt_path:
            aggregate_bytes += len(data)
    return artifacts


__all__ = ["collect_artifacts", "materialize_under", "safe_relative_path"]
