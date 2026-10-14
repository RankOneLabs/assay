"""Filesystem boundary shared by every handle that materializes a package
onto a real directory (``pier_adapter.write_task_directory`` and
``container._materialize``) or reads a trial's output back off one
(``collect_artifacts``).

Deliberately local rather than imported from ``assay.repository``: this
bridge project has no dependency edge back onto ``assay`` (see README.md).
"""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory


class ArtifactCollectionRejected(ValueError):
    """Bounded rejected evidence, available even when collection aborts."""

    def __init__(
        self,
        cause: str,
        message: str,
        *,
        artifacts: dict[str, bytes] | None = None,
        rejected_path: str | None = None,
    ) -> None:
        super().__init__(message)
        self.cause = cause
        self.artifacts = artifacts or {}
        self.rejected_path = rejected_path


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


@dataclass(frozen=True, slots=True)
class SubmissionPatch:
    patch: bytes
    baseline_tree_digest: str
    final_tree_digest: str


def regular_tree(root: Path) -> dict[str, bytes]:
    """Read a host-visible tree without following candidate-controlled links."""
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        raw_relative = path.relative_to(root).as_posix()
        try:
            relative = safe_relative_path(raw_relative).as_posix()
        except ValueError as error:
            raise ArtifactCollectionRejected(
                "traversal", str(error), rejected_path=raw_relative
            ) from error
        if path.is_symlink():
            raise ArtifactCollectionRejected(
                "escaping_symlink",
                f"escaping symlink in submission: {relative}",
                artifacts=files,
                rejected_path=relative,
            )
        if path.is_dir():
            continue
        if not path.is_file():
            raise ArtifactCollectionRejected(
                "out_of_scope_edit",
                f"non-regular entry in submission: {relative}",
                artifacts=files,
                rejected_path=relative,
            )
        data = path.read_bytes()
        if b"\x00" in data:
            raise ArtifactCollectionRejected(
                "binary_payload",
                f"binary payload in submission: {relative}",
                artifacts=files,
                rejected_path=relative,
            )
        try:
            data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise ArtifactCollectionRejected(
                "binary_payload",
                f"binary payload in submission: {relative}",
                artifacts=files,
                rejected_path=relative,
            ) from error
        files[relative] = data
    return files


def tree_digest(files: Mapping[str, bytes]) -> str:
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda value: value.encode("utf-8")):
        safe_relative_path(path)
        digest.update(path.encode("utf-8") + b"\x00100644\x00" + files[path] + b"\x00")
    return f"sha256:{digest.hexdigest()}"


def submission_patch(baseline: Path, final: Path) -> SubmissionPatch:
    """Build a deterministic Git patch from observed trees, never an edit claim."""
    before = regular_tree(baseline)
    after = regular_tree(final)
    with TemporaryDirectory(prefix="assay-patch-") as temporary:
        checkout = Path(temporary)
        subprocess.run(["git", "init", "-q", str(checkout)], check=True)
        # The candidate can edit .gitattributes. Its text/filter rules must
        # never rewrite the bytes being observed or the patch cannot replay.
        (checkout / ".git" / "info" / "attributes").write_text(
            "* -text -filter -ident diff\n", encoding="ascii"
        )
        for path, data in before.items():
            target = checkout / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o644)
        subprocess.run(
            ["git", "-c", "core.autocrlf=false", "add", "--all"], cwd=checkout, check=True
        )
        for path in before:
            (checkout / path).unlink()
        for path, data in after.items():
            target = checkout / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o644)
        new_paths = sorted(set(after) - set(before))
        if new_paths:
            subprocess.run(
                ["git", "-c", "core.autocrlf=false", "add", "-N", "--", *new_paths],
                cwd=checkout,
                check=True,
            )
        diff = subprocess.run(
            [
                "git",
                "-c",
                "core.autocrlf=false",
                "-c",
                "core.quotePath=false",
                "-c",
                "diff.algorithm=myers",
                "diff",
                "--binary",
                "--full-index",
                "--unified=3",
                "--no-renames",
                "--no-ext-diff",
                "--no-textconv",
            ],
            cwd=checkout,
            capture_output=True,
            check=True,
        ).stdout
        # Git's patch carries no clock or checkout path; all source modes are fixed.
    return SubmissionPatch(diff, tree_digest(before), tree_digest(after))


def collect_artifacts(
    root: Path,
    *,
    max_bytes: int,
    max_aggregate_bytes: int,
    max_entries: int,
    aggregate_exempt_path: str,
    excluded_roots: frozenset[str] = frozenset(),
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
            raise ArtifactCollectionRejected(
                "entry_limit",
                "trial submission exceeds the filesystem entry limit",
                rejected_path=path.relative_to(root).as_posix(),
            )

    artifacts: dict[str, bytes] = {}
    aggregate_bytes = 0
    for path in sorted(paths):
        if path.relative_to(root).parts[0] in excluded_roots:
            continue
        if path.is_symlink():
            raise ArtifactCollectionRejected(
                "escaping_symlink",
                f"symlink in submission: {path.relative_to(root)}",
                artifacts=artifacts,
                rejected_path=path.relative_to(root).as_posix(),
            )
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if path.lstat().st_size > max_bytes:
            raise ArtifactCollectionRejected(
                "oversized_artifact",
                f"trial artifact exceeds the byte limit: {relative}",
                artifacts=artifacts,
                rejected_path=relative,
            )
        try:
            safe_relative_path(relative)
        except ValueError as error:
            raise ArtifactCollectionRejected(
                "traversal", str(error), artifacts=artifacts, rejected_path=relative
            ) from error
        remaining = (
            max_bytes
            if relative == aggregate_exempt_path
            else min(max_bytes, max_aggregate_bytes - aggregate_bytes)
        )
        with path.open("rb") as artifact_file:
            data = artifact_file.read(remaining + 1)
        if len(data) > remaining:
            if relative == aggregate_exempt_path or remaining == max_bytes:
                raise ArtifactCollectionRejected(
                    "oversized_artifact",
                    f"trial artifact exceeds the byte limit: {relative}",
                    artifacts={**artifacts, relative: data[:max_bytes]},
                    rejected_path=relative,
                )
            raise ArtifactCollectionRejected(
                "aggregate_artifact_limit",
                "trial artifacts exceed the aggregate byte limit",
                artifacts={**artifacts, relative: data[:remaining]},
                rejected_path=relative,
            )
        artifacts[relative] = data
        if relative != aggregate_exempt_path:
            aggregate_bytes += len(data)
    return artifacts


__all__ = ["collect_artifacts", "materialize_under", "safe_relative_path"]
