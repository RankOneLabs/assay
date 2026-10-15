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
from typing import Literal

from assay.canonical import canonical_json, digest_bytes
from assay.repository import (
    DEFAULT_MAX_REPOSITORY_BYTES,
    DEFAULT_MAX_REPOSITORY_FILES,
    validate_repository,
    validate_source_tree,
)

WORKSPACE_PREFIX = "workspace"
INSTRUCTION_PATH = "instruction.md"
SUBMISSION_CONTRACT_PATH = "submission/CONTRACT.md"

# Synthetic audit markers are bound into each worker configuration. A fixture
# containing one of these markers cannot cross the final dispatch gate.
FORBIDDEN_SENTINELS: tuple[tuple[str, str], ...] = (
    ("private_documentation", "SENTINEL_PRIVATE_DOCUMENTATION_1a2b"),
    ("transcript", "SENTINEL_TRANSCRIPT_3c4d"),
    ("credential", "SENTINEL_CREDENTIAL_5e6f"),
    ("other_arm", "SENTINEL_OTHER_ARM_HIDDEN_3c4d"),
    ("hidden_test", "SENTINEL_HIDDEN_TEST_5e6f"),
    ("reference_solution", "SENTINEL_REFERENCE_SOLUTION_7g8h"),
)

SUBMISSION_CONTRACT = (
    "# Submission contract\n\n"
    "Edit repository files in `/submission/worktree`, a writable copy of the "
    "arm baseline. The host derives the final patch and tree digest from that "
    "directory. Call `submit_output` exactly once when done; an empty source "
    "is a valid no-op. `/scratch` is discarded when the trial ends.\n"
)


PackageLayout = Literal["submission-worktree", "repository-agent"]

REPOSITORY_AGENT_WORKSPACE = (
    "## Workspace\n\n"
    "The repository is your working directory, `/workspace`. Edit its files in "
    "place; the file tree you leave there is your submission. Call "
    "`submit_output` with a short summary when you are done.\n"
)


def render_instruction(task: str, layout: PackageLayout = "submission-worktree") -> str:
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
    if layout == "repository-agent":
        # The repository agent edits /workspace directly; there is no
        # submission worktree or contract file in its package.
        return f"# Task\n\n{stripped}\n\n{REPOSITORY_AGENT_WORKSPACE}"
    return (
        "# Task\n\n"
        f"{stripped}\n\n"
        "## Workspace\n\n"
        "Your baseline is mounted read-only at the workspace root. Edit the "
        "writable repository copy at `/submission/worktree`. "
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
    max_repository_files: int = DEFAULT_MAX_REPOSITORY_FILES,
    max_repository_bytes: int = DEFAULT_MAX_REPOSITORY_BYTES,
    layout: PackageLayout = "submission-worktree",
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
    files: dict[str, str] = {INSTRUCTION_PATH: render_instruction(task, layout)}
    if layout == "submission-worktree":
        files[SUBMISSION_CONTRACT_PATH] = SUBMISSION_CONTRACT
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
    forbidden_substrings: Mapping[str, str] | tuple[str, ...] = (),
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
    # boundary exists to prevent. Every path must also already use its
    # canonical POSIX spelling. PurePosixPath and the filesystem normalize
    # aliases such as ``workspace/./instruction.md`` only after a raw-string
    # collision check, which would otherwise let the alias overwrite the
    # sealed instruction during materialization. Unmountable is the safe
    # answer; there is no ordering that makes the result unambiguous.
    mounted: dict[str, str] = {}
    for path, content in package.files:
        if path not in _ALLOWED_NON_REPOSITORY_PATHS and not path.startswith(prefix):
            raise ValueError(f"package entry is outside the allowlist: {path}")
        parsed_path = PurePosixPath(path)
        if (
            parsed_path.is_absolute()
            or any(part in {"", ".", ".."} for part in parsed_path.parts)
            or parsed_path.as_posix() != path
        ):
            raise ValueError(f"package entry has an unsafe path: {path}")
        relative = path[len(prefix) :] if path.startswith(prefix) else path
        mounted_path = PurePosixPath(relative).as_posix()
        if mounted_path in mounted:
            raise ValueError(
                f"package entries {mounted[mounted_path]!r} and {path!r} collide at the "
                f"mounted path {mounted_path!r}"
            )
        mounted[mounted_path] = path
        sentinels = (
            forbidden_substrings.items()
            if isinstance(forbidden_substrings, Mapping)
            else ((sentinel, sentinel) for sentinel in forbidden_substrings)
        )
        for category, sentinel in sentinels:
            if sentinel in content:
                raise ValueError(f"package entry carries forbidden sentinel ({category}): {path}")


def non_repository_entries(package: SealedPackage) -> dict[str, str]:
    """Project a package onto everything except its repository content.

    Two packages for the same cell but different arms must be byte-identical
    here: the instruction and submission contract never vary with the
    selected arm's identity or content.
    """
    prefix = f"{WORKSPACE_PREFIX}/"
    return {path: content for path, content in package.files if not path.startswith(prefix)}
