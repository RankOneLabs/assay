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
from pathlib import Path

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
    """Deterministic instruction text: no arm id, digest, or object metadata."""
    stripped = task.strip()
    if not stripped:
        raise ValueError("task instruction must be nonblank")
    return (
        "# Task\n\n"
        f"{stripped}\n\n"
        "## Workspace\n\n"
        f"Your repository is mounted read-only under `{WORKSPACE_PREFIX}/`. "
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


def _manifest_digest(files: Mapping[str, str]) -> str:
    entries = [[path, digest_bytes(content.encode("utf-8"))] for path, content in files.items()]
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
        manifest_digest=_manifest_digest(files),
    )


def repository_only_entries(package: SealedPackage) -> dict[str, str]:
    """Project a package onto only its ``workspace/`` (repository) entries."""
    prefix = f"{WORKSPACE_PREFIX}/"
    return {path: content for path, content in package.files if path.startswith(prefix)}


def non_repository_entries(package: SealedPackage) -> dict[str, str]:
    """Project a package onto everything except its repository content.

    Two packages for the same cell but different arms must be byte-identical
    here: the instruction and submission contract never vary with the
    selected arm's identity or content.
    """
    prefix = f"{WORKSPACE_PREFIX}/"
    return {path: content for path, content in package.files if not path.startswith(prefix)}
