"""Deterministic sealed Harbor package boundary for one Pier trial per cell.

A package is built only from named, allowlisted files — the rendered
instruction, the selected arm's repository under a neutral path, and the
submission contract. Nothing else the operator holds (other arms, evaluator
fixtures, hidden tests, object-store metadata, an arm identifier) is ever
read into it. A realization directory or the repository root is never used
as a Docker build context; every file entering the package passes through
``assay.repository.validate_source_tree`` first.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from assay.canonical import canonical_json, digest_bytes
from assay.repository import validate_repository, validate_source_tree

WORKSPACE_PREFIX = "workspace"
INSTRUCTION_PATH = "instruction.md"
SUBMISSION_CONTRACT_PATH = "submission/CONTRACT.md"

SUBMISSION_CONTRACT = (
    "# Submission contract\n\n"
    "Write your final source to `/submission/output` as UTF-8 text. Do not "
    "write anywhere else in `/submission`; `/scratch` is discarded when the "
    "trial ends. Call `submit_output` exactly once with the same content.\n"
)


def render_instruction(task: str) -> str:
    """Deterministic instruction text: no arm id, digest, or object metadata.

    The workspace sentence describes the layout the model actually sees, not
    the package's own path scheme. ``WORKSPACE_PREFIX`` namespaces repository
    entries *inside the package*; the bridge strips it when materializing the
    mount, so the repository lands beside this instruction rather than in a
    ``workspace/`` subdirectory. Naming the prefix here sent the model
    looking in a directory that does not exist in the container.
    """
    stripped = task.strip()
    if not stripped:
        raise ValueError("task instruction must be nonblank")
    return (
        "# Task\n\n"
        f"{stripped}\n\n"
        "## Workspace\n\n"
        "Your repository is mounted read-only at the workspace root: the files "
        "beside this instruction are the repository itself. "
        f"See `{SUBMISSION_CONTRACT_PATH}` for how to submit your answer.\n"
    )


@dataclass(frozen=True, slots=True)
class SealedPackage:
    """A deterministic, fully-materialized model-visible file set."""

    cell_id: str
    files: tuple[tuple[str, str], ...]
    manifest_digest: str

    def as_mapping(self) -> dict[str, str]:
        return dict(self.files)


def manifest_digest(files: Mapping[str, str]) -> str:
    """The sealed package's content identity, mirrored byte-for-byte by the bridge.

    Both sides of the wire contract compute this value independently --
    ``integrations/pier``'s ``container.package_digest`` reimplements it
    locally, because that project has no import edge back onto ``assay`` --
    and ``TrialRequest.package_digest`` is only meaningful if the two agree
    exactly. ``tests/fixtures/pier_wire_contract.json`` pins the expected
    output for a fixed set of packages and is asserted from both test
    suites; changing this function without changing the bridge's copy (or
    the fixture) fails on both sides.

    Entries are sorted here rather than inherited from the caller's mapping
    order: ``canonical_json`` preserves array order, so an unsorted mapping
    would hash differently from the same content sorted, and the bridge
    receives a materialized package with no memory of how it was built.
    """
    entries = [
        [path, digest_bytes(content.encode("utf-8"))] for path, content in sorted(files.items())
    ]
    return digest_bytes(canonical_json(entries))


def build_package(
    *,
    cell_id: str,
    task: str,
    repository_root: Path,
    max_repository_files: int = 200,
    max_repository_bytes: int = 1_000_000,
) -> SealedPackage:
    """Build the sealed package for one cell from an on-disk realization.

    Repeated calls with the same inputs are byte-identical: this function is
    a pure projection of ``(task, repository_root's validated content)``,
    and ``cell_id`` is carried only as package metadata, never written into
    any file or path.
    """
    repository = validate_source_tree(
        repository_root, max_files=max_repository_files, max_total_bytes=max_repository_bytes
    )
    files: dict[str, str] = {
        INSTRUCTION_PATH: render_instruction(task),
        SUBMISSION_CONTRACT_PATH: SUBMISSION_CONTRACT,
    }
    for path, content in repository.items():
        files[f"{WORKSPACE_PREFIX}/{path}"] = content
    files = validate_repository(
        files,
        max_files=max_repository_files + 2,
        max_total_bytes=max_repository_bytes + len(SUBMISSION_CONTRACT) + 65_536,
    )
    return SealedPackage(
        cell_id=cell_id,
        files=tuple(sorted(files.items())),
        manifest_digest=manifest_digest(files),
    )


def repository_only_entries(package: SealedPackage) -> dict[str, str]:
    """Project a package onto only its ``workspace/`` (repository) entries."""
    prefix = f"{WORKSPACE_PREFIX}/"
    return {path: content for path, content in package.files if path.startswith(prefix)}


_ALLOWED_NON_REPOSITORY_PATHS = frozenset({INSTRUCTION_PATH, SUBMISSION_CONTRACT_PATH})


def gate_package(
    package: SealedPackage,
    *,
    expected_digest: str,
    forbidden_substrings: tuple[str, ...] = (),
) -> None:
    """The last check before a package's digest is handed to ``Trial.create``.

    Fails closed on any of: a recomputed digest that does not match both the
    package's own stored digest and what the caller is about to authorize
    (content was substituted while ``manifest_digest`` was left unchanged, or
    the package was rebuilt or tampered with between build and dispatch), a
    duplicate path, a path outside the fixed allowlist or containing a
    traversal segment (the workspace prefix plus the instruction and
    submission contract), two entries that collide once the workspace prefix
    is stripped for the mount, or any forbidden substring appearing in file
    content — a sentinel audit hook a caller can use to check content
    against hidden tests, other arms, evaluator fixtures, or object-store
    metadata it holds out of band.
    """
    current_files = dict(package.files)
    if len(current_files) != len(package.files):
        raise ValueError("package entries contain a duplicate path")
    actual_digest = manifest_digest(current_files)
    if actual_digest != package.manifest_digest or actual_digest != expected_digest:
        raise ValueError("package digest does not match the digest being authorized")
    prefix = f"{WORKSPACE_PREFIX}/"
    # The bridge mounts the package with the workspace prefix stripped, so
    # the repository sits beside the instruction rather than under it. That
    # projection is only safe while it is injective: a repository that
    # happens to contain a file named ``instruction.md`` would otherwise
    # arrive at the same mounted path as the sealed instruction, and the
    # loser is decided by nothing more principled than iteration order. The
    # repository file wins, which means an arm's own content can replace the
    # task the model is given -- the one substitution this whole sealed
    # boundary exists to prevent. Unmountable is the safe answer; there is no
    # ordering that makes the result unambiguous.
    mounted: dict[str, str] = {}
    for path, content in package.files:
        if path not in _ALLOWED_NON_REPOSITORY_PATHS and not path.startswith(prefix):
            raise ValueError(f"package entry is outside the allowlist: {path}")
        parts = PurePosixPath(path).parts
        if PurePosixPath(path).is_absolute() or any(part in {"", ".", ".."} for part in parts):
            raise ValueError(f"package entry has an unsafe path: {path}")
        relative = path[len(prefix) :] if path.startswith(prefix) else path
        if relative in mounted:
            raise ValueError(
                f"package entries {mounted[relative]!r} and {path!r} collide at the "
                f"mounted path {relative!r}"
            )
        mounted[relative] = path
        for sentinel in forbidden_substrings:
            if sentinel in content:
                raise ValueError(f"package entry carries a forbidden sentinel: {path}")


def non_repository_entries(package: SealedPackage) -> dict[str, str]:
    """Project a package onto everything except its repository content.

    Two packages for the same cell but different arms must be byte-identical
    here: the instruction and submission contract never vary with the
    selected arm's identity or content.
    """
    prefix = f"{WORKSPACE_PREFIX}/"
    return {path: content for path, content in package.files if not path.startswith(prefix)}
