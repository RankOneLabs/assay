"""Load the pinned slice and construct complete or deliberately incomplete renames."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from workflow_edit.fixture import read_tree

from assay.investigations.workflow_correctness import workflow_tree_digest
from assay.repository import validate_repository
from verification_pilot.migrations import MIGRATIONS, generate_rename

PILOT_EDIT = Path(__file__).resolve().parent / "fixtures" / "pilot-edit"
OAKRIDGE_COMMIT = "f3b3ffca43e43672ff2f58ab797d65c7532aaed8"
SOURCE_TREE_COMMIT = "a20f94dd19c5b5d29939f4ed34a650a6d7368908"
PINNED_TREE_DIGEST = "sha256:a4039feafdf6061711fc040281108a65076fbbd1cfa8d3aacaac935374c6cfca"
MAX_FILES = 200
MAX_BYTES = 1_000_000


@dataclass(frozen=True, slots=True)
class PilotFixture:
    repository: dict[str, str]
    tree_digest: str
    renamed: dict[str, dict[str, str]]


def load_fixture(root: Path = PILOT_EDIT) -> PilotFixture:
    """Read, bound, validate and digest the committed source before generating."""
    repository = validate_repository(
        read_tree(root / "repository"),
        max_files=MAX_FILES,
        max_total_bytes=MAX_BYTES,
    )
    digest = workflow_tree_digest(repository)
    if digest != PINNED_TREE_DIGEST:
        raise ValueError(f"pilot source tree digest changed: {digest}")
    renamed = {migration.name: generate_rename(repository, migration) for migration in MIGRATIONS}
    return PilotFixture(repository=repository, tree_digest=digest, renamed=renamed)
