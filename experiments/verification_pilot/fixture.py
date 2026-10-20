"""Load the pinned slice and construct complete or deliberately incomplete renames."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from assay.investigations.workflow_correctness import workflow_tree_digest
from assay.repository import validate_repository
from verification_pilot.fixtures import (
    RAW_REPO,
    BaseSubject,
    read_raw_repository,
    whole_word_pattern,
)
from verification_pilot.migrations import MIGRATIONS, generate_rename

OAKRIDGE_COMMIT = "f3b3ffca43e43672ff2f58ab797d65c7532aaed8"
SOURCE_TREE_COMMIT = "a20f94dd19c5b5d29939f4ed34a650a6d7368908"
DESIGN_COMMIT = "03b11bb0c5ea46f0ba497a0f0679622b096cb4d0"
PINNED_TREE_DIGEST = "sha256:a4039feafdf6061711fc040281108a65076fbbd1cfa8d3aacaac935374c6cfca"
MAX_FILES = 200
MAX_BYTES = 1_000_000


@dataclass(frozen=True, slots=True)
class PilotFixture:
    repository: dict[str, str]
    tree_digest: str
    renamed: dict[str, dict[str, str]]


def load_fixture(root: Path = RAW_REPO) -> PilotFixture:
    """Read, bound, validate and digest the committed source before generating."""
    repository = validate_repository(
        read_raw_repository(root),
        max_files=MAX_FILES,
        max_total_bytes=MAX_BYTES,
    )
    digest = workflow_tree_digest(repository)
    if digest != PINNED_TREE_DIGEST:
        raise ValueError(f"pilot source tree digest changed: {digest}")
    renamed = {migration.name: generate_rename(repository, migration) for migration in MIGRATIONS}
    return PilotFixture(repository=repository, tree_digest=digest, renamed=renamed)


def subject_repository(subject: BaseSubject, fixture: PilotFixture) -> dict[str, str]:
    """Plant one remnant and two historical decoy carriers for this subject."""
    repository = dict(fixture.renamed[subject.migration.name])
    if subject.location is not None:
        source, count = whole_word_pattern(subject.migration.new_symbol).subn(
            subject.migration.old_symbol, repository[subject.location], count=1,
        )
        if count != 1:
            raise ValueError(f"{subject.id}: cannot plant remnant")
        repository[subject.location] = source
    repository["CHANGELOG.md"] = (
        f"# Historical notes\n\nThe old {subject.migration.old_symbol} spelling was used "
        "before this migration.\n"
    )
    repository["docs/migration.md"] = (
        f"# Migration note\n\nReferences to {subject.migration.old_symbol} in this "
        "document describe the previous API.\n"
    )
    return repository
