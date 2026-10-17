"""Filesystem boundary shared by every handle that materializes a package
onto a real directory (``pier_adapter.write_task_directory`` and
``container._materialize``) or reads a trial's output back off one
(``collect_artifacts``).

Deliberately local rather than imported from ``assay.repository``: this
bridge project has no dependency edge back onto ``assay`` (see README.md).
"""

from __future__ import annotations

import errno
import hashlib
import io
import os
import re
import stat
import subprocess
import tarfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

MAX_ARTIFACT_BYTES = 8_000_000
MAX_AGGREGATE_ARTIFACT_BYTES = 32_000_000
MAX_SUBMISSION_ENTRIES = 4_096
# A path component Git reserves for its own metadata: ``.git`` in any ASCII
# case and its NTFS spellings (``git~1``, trailing dots or spaces, a stream
# suffix), all refused by Git's default ``verify_path``. At any depth Git
# either drops such a path from the index silently or fails the whole ``add``,
# so a tree containing one can never round-trip through a patch.
_RESERVED_GIT_COMPONENT = re.compile(r"(?:\.git|git~1)[. ]*(?::.*)?", re.IGNORECASE | re.ASCII)


class ArtifactCollectionRejected(ValueError):
    """Bounded rejected evidence, available even when collection aborts."""

    def __init__(
        self,
        cause: str,
        message: str,
        *,
        artifacts: dict[str, bytes] | None = None,
        rejected_path: str | None = None,
        origin: str = "submission",
    ) -> None:
        super().__init__(message)
        self.cause = cause
        self.artifacts = artifacts or {}
        self.rejected_path = rejected_path
        self.origin = origin


def _read_regular_nofollow(
    root: Path, relative: str, limit: int, *, origin: str, reject_size: int | None = None
) -> tuple[bytes, int]:
    """Open every component relative to the preceding directory, then bound the read."""
    parts = safe_relative_path(relative).parts
    descriptors: list[int] = []
    try:
        descriptors.append(os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW))
        for part in parts[:-1]:
            descriptors.append(os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=descriptors[-1],
            ))
        leaf = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=descriptors[-1],
        )
        descriptors.append(leaf)
        metadata = os.fstat(leaf)
        if not stat.S_ISREG(metadata.st_mode):
            raise ArtifactCollectionRejected(
                "out_of_scope_edit", f"non-regular entry in submission: {relative}",
                rejected_path=relative, origin=origin,
            )
        if reject_size is not None and metadata.st_size > reject_size:
            return b"", metadata.st_size
        with os.fdopen(os.dup(leaf), "rb") as source:
            return source.read(limit + 1), metadata.st_size
    except OSError as error:
        cause = (
            "escaping_symlink"
            if error.errno in {errno.ELOOP, errno.ENOTDIR}
            else "out_of_scope_edit"
        )
        raise ArtifactCollectionRejected(
            cause, f"unsafe entry in submission: {relative}",
            rejected_path=relative, origin=origin,
        ) from error
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


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
    """Read a bounded host-visible tree without following candidate-controlled links."""
    files: dict[str, bytes] = {}
    if root.is_symlink():
        raise ArtifactCollectionRejected(
            "escaping_symlink", f"symlinked working-copy root: {root}",
            origin="working_copy",
        )
    if not root.is_dir():
        raise ArtifactCollectionRejected(
            "out_of_scope_edit", f"working-copy root is not a directory: {root}",
            origin="working_copy",
        )
    paths: list[Path] = []
    for path in root.rglob("*"):
        paths.append(path)
        if len(paths) > MAX_SUBMISSION_ENTRIES:
            raise ArtifactCollectionRejected(
                "entry_limit", "working copy exceeds the filesystem entry limit",
                rejected_path=path.relative_to(root).as_posix(), origin="working_copy",
            )
    aggregate_bytes = 0
    for path in sorted(paths):
        raw_relative = path.relative_to(root).as_posix()
        try:
            relative = safe_relative_path(raw_relative).as_posix()
        except ValueError as error:
            raise ArtifactCollectionRejected(
                "traversal", str(error), artifacts=files,
                rejected_path=raw_relative, origin="working_copy"
            ) from error
        if any(_RESERVED_GIT_COMPONENT.fullmatch(part) for part in relative.split("/")):
            raise ArtifactCollectionRejected(
                "out_of_scope_edit", f"reserved Git metadata path in submission: {relative}",
                artifacts=files, rejected_path=relative, origin="working_copy",
            )
        if stat.S_ISDIR(path.lstat().st_mode):
            continue
        remaining = MAX_AGGREGATE_ARTIFACT_BYTES - aggregate_bytes
        try:
            data, size = _read_regular_nofollow(
                root, relative, min(MAX_ARTIFACT_BYTES, remaining), origin="working_copy"
            )
        except ArtifactCollectionRejected as error:
            error.artifacts = dict(files)
            raise
        if size > MAX_ARTIFACT_BYTES or size > remaining:
            cause = (
                "oversized_artifact" if size > MAX_ARTIFACT_BYTES
                else "aggregate_artifact_limit"
            )
            raise ArtifactCollectionRejected(
                cause, f"working-copy file exceeds the byte limit: {relative}",
                artifacts={**files, relative: data[:min(MAX_ARTIFACT_BYTES, remaining)]},
                rejected_path=relative, origin="working_copy",
            )
        if len(data) > MAX_ARTIFACT_BYTES or len(data) > remaining:
            retained = data[:min(MAX_ARTIFACT_BYTES, remaining)]
            cause = (
                "oversized_artifact" if len(data) > MAX_ARTIFACT_BYTES
                else "aggregate_artifact_limit"
            )
            raise ArtifactCollectionRejected(
                cause, f"working-copy file exceeds the byte limit: {relative}",
                artifacts={**files, relative: retained},
                rejected_path=relative, origin="working_copy",
            )
        if b"\x00" in data:
            raise ArtifactCollectionRejected(
                "binary_payload",
                f"binary payload in submission: {relative}",
                artifacts=files,
                rejected_path=relative,
                origin="working_copy",
            )
        try:
            data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise ArtifactCollectionRejected(
                "binary_payload",
                f"binary payload in submission: {relative}",
                artifacts=files,
                rejected_path=relative,
                origin="working_copy",
            ) from error
        files[relative] = data
        aggregate_bytes += len(data)
    return files


def extract_workspace_archive(archive: bytes, root: Path) -> None:
    """Materialize a candidate's tar stream as regular files only, within bounds.

    Every member is checked before anything is written for it: a link of any
    kind, a special file, a non-canonical or escaping path, or an entry past
    the count and byte ceilings raises a typed working-copy rejection that
    carries the files read so far. Nothing is ever followed or extracted
    through Python's generic ``extractall``.
    """
    files: dict[str, bytes] = {}
    entries = 0
    aggregate_bytes = 0
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as stream:
        for member in stream:
            raw = member.name.removeprefix("./").rstrip("/")
            if raw in ("", "."):
                continue
            entries += 1
            if entries > MAX_SUBMISSION_ENTRIES:
                raise ArtifactCollectionRejected(
                    "entry_limit", "working copy exceeds the filesystem entry limit",
                    artifacts=files, rejected_path=raw, origin="working_copy",
                )
            try:
                relative = safe_relative_path(raw)
            except ValueError as error:
                raise ArtifactCollectionRejected(
                    "traversal", str(error), artifacts=files, rejected_path=raw,
                    origin="working_copy",
                ) from error
            if member.issym() or member.islnk():
                raise ArtifactCollectionRejected(
                    "escaping_symlink", f"link in submission: {raw}",
                    artifacts=files, rejected_path=raw, origin="working_copy",
                )
            target = root / relative
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise ArtifactCollectionRejected(
                    "out_of_scope_edit", f"non-regular entry in submission: {raw}",
                    artifacts=files, rejected_path=raw, origin="working_copy",
                )
            if member.size > MAX_ARTIFACT_BYTES:
                raise ArtifactCollectionRejected(
                    "oversized_artifact", f"working-copy file exceeds the byte limit: {raw}",
                    artifacts=files, rejected_path=raw, origin="working_copy",
                )
            aggregate_bytes += member.size
            if aggregate_bytes > MAX_AGGREGATE_ARTIFACT_BYTES:
                raise ArtifactCollectionRejected(
                    "aggregate_artifact_limit", "working copy exceeds the aggregate byte limit",
                    artifacts=files, rejected_path=raw, origin="working_copy",
                )
            source = stream.extractfile(member)
            data = source.read() if source is not None else b""
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o644)
            files[raw] = data


# Dependency manifests and test configuration a submission may never change.
PROTECTED_NAMES = frozenset(
    {"package.json", "package-lock.json", "bun.lock", "bun.lockb", "bunfig.toml", "tsconfig.json"}
)


def check_submission_scope(
    before: Mapping[str, bytes],
    after: Mapping[str, bytes],
    *,
    writable_prefixes: tuple[str, ...],
) -> None:
    """Reject any added, changed, or deleted path outside the declared scope.

    An empty scope places no restriction. Otherwise a change to a dependency
    manifest or test configuration anywhere, even beneath a writable prefix,
    or to a test outside the writable prefixes is ``tampering``; any other
    stray path is ``out_of_scope_edit``. The changed files are retained on
    the rejection as evidence.
    """
    if not writable_prefixes:
        return
    changed = sorted(
        path
        for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    )
    for path in changed:
        # A nested manifest or tsconfig changes resolution as surely as the root one.
        protected = PurePosixPath(path).name in PROTECTED_NAMES
        if path.startswith(writable_prefixes) and not protected:
            continue
        cause = (
            "tampering"
            if protected or path.startswith("tests/")
            else "out_of_scope_edit"
        )
        raise ArtifactCollectionRejected(
            cause,
            f"submission changes a path outside its declared scope: {path}",
            artifacts={item: after[item] for item in changed if item in after},
            rejected_path=path,
            origin="working_copy",
        )


def tree_digest(files: Mapping[str, bytes]) -> str:
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda value: value.encode("utf-8")):
        safe_relative_path(path)
        digest.update(path.encode("utf-8") + b"\x00100644\x00" + files[path] + b"\x00")
    return f"sha256:{digest.hexdigest()}"


def _git(checkout: Path, *args: str) -> bytes:
    """Run Git with none of the host's configuration or ``GIT_*`` environment.

    A global or system ``core.excludesFile``, a template's ``info/exclude``, or
    an inherited ``GIT_DIR`` would otherwise decide which observed files reach
    the patch, so capture would depend on whose machine ran it.
    """
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    return subprocess.run(
        [
            "git",
            "-c",
            f"core.excludesFile={os.devnull}",
            "-c",
            "core.autocrlf=false",
            "-c",
            "init.defaultBranch=main",
            *args,
        ],
        cwd=checkout,
        env=environment,
        capture_output=True,
        check=True,
    ).stdout


def submission_patch(baseline: Path, final: Path) -> SubmissionPatch:
    """Build a deterministic Git patch from observed trees, never an edit claim."""
    before = regular_tree(baseline)
    after = regular_tree(final)
    with TemporaryDirectory(prefix="assay-patch-") as temporary:
        checkout = Path(temporary)
        _git(checkout, "init", "-q", "--template=", ".")
        # The candidate can edit .gitattributes. Its text/filter rules must
        # never rewrite the bytes being observed or the patch cannot replay.
        (checkout / ".git" / "info").mkdir(exist_ok=True)
        (checkout / ".git" / "info" / "attributes").write_text(
            "* -text -filter -ident diff\n", encoding="ascii"
        )
        for path, data in before.items():
            target = checkout / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o644)
        # ``-f`` on both adds: a .gitignore in the observed tree is content to
        # capture, never a filter on what is captured.
        _git(checkout, "add", "-f", "--all")
        for path in before:
            (checkout / path).unlink()
        for path, data in after.items():
            target = checkout / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o644)
        new_paths = sorted(set(after) - set(before))
        if new_paths:
            _git(checkout, "add", "-f", "-N", "--", *new_paths)
        # Every observed path must be indexed or the patch silently omits it;
        # fail capture instead of publishing a patch that cannot replay.
        indexed = {path for path in _git(checkout, "ls-files", "-z").split(b"\x00") if path}
        if indexed != {path.encode("utf-8") for path in before.keys() | after.keys()}:
            raise ValueError("patch_capture_incomplete")
        diff = _git(
            checkout,
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
        )
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
        if stat.S_ISDIR(path.lstat().st_mode):
            continue
        relative = path.relative_to(root).as_posix()
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
        try:
            data, size = _read_regular_nofollow(
                root, relative, remaining, origin="submission", reject_size=max_bytes
            )
        except ArtifactCollectionRejected as error:
            error.artifacts = dict(artifacts)
            raise
        if size > max_bytes and len(data) <= remaining:
            raise ArtifactCollectionRejected(
                "oversized_artifact", f"trial artifact exceeds the byte limit: {relative}",
                artifacts=artifacts, rejected_path=relative,
            )
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
