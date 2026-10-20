"""Load the committed smoke-edit fixture: repository, task, frozen test groups, patches."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from assay.investigations.workflow_correctness import WorkflowTestGroup, workflow_tree_digest
from assay.repository import validate_repository
from workflow_edit.settings import SMOKE_EDIT_SUBJECT_ID as SMOKE_EDIT_SUBJECT_ID

SMOKE_EDIT = Path(__file__).resolve().parent / "fixtures" / "smoke-edit"
# Matches the README's limits; the repository is 62 files and 348,936 bytes.
MAX_REPOSITORY_FILES = 200
MAX_REPOSITORY_BYTES = 1_000_000
VISIBLE_PREFIX = "tests/visible/"
GROUP_COMMANDS: Mapping[str, tuple[str, ...]] = {
    "hidden_regression": ("bun", "test", "./tests/hidden/regression"),
    "new_behavior": ("bun", "test", "./tests/hidden/new-behavior"),
}


def read_tree(root: Path) -> dict[str, str]:
    """Every regular file under ``root`` as UTF-8 text, keyed by POSIX path."""
    files = {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
    return validate_repository(
        files, max_files=MAX_REPOSITORY_FILES, max_total_bytes=MAX_REPOSITORY_BYTES
    )


def materialize(root: Path, repository: Mapping[str, str], patch: str | None = None) -> None:
    """Write a repository under ``root``, then apply a candidate or reference patch."""
    for path, text in repository.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    if patch is not None:
        subprocess.run(
            ["git", "apply", "--allow-empty", "-"], cwd=root, input=patch.encode(), check=True
        )


@dataclass(frozen=True, slots=True)
class SmokeEditFixture:
    repository: dict[str, str]
    task: str
    groups: tuple[WorkflowTestGroup, WorkflowTestGroup, WorkflowTestGroup]
    reference_patch: str
    negative_patch: str

    @property
    def tree_digest(self) -> str:
        return workflow_tree_digest(self.repository)


def visible_group(repository: Mapping[str, str]) -> WorkflowTestGroup:
    """The baseline's own visible tests, restored over the candidate and run by name.

    Naming the frozen files keeps a candidate's added tests out of the
    regression verdict, and restoring them keeps its edits out of it.
    """
    files = {path: text for path, text in repository.items() if path.startswith(VISIBLE_PREFIX)}
    tests = sorted(f"./{path}" for path in files if path.endswith(".test.ts"))
    return WorkflowTestGroup(
        name="visible_regression", files=files, command=("bun", "test", *tests), restores=True
    )


def load_fixture(root: Path = SMOKE_EDIT) -> SmokeEditFixture:
    repository = read_tree(root / "repository")
    groups = (
        visible_group(repository),
        WorkflowTestGroup(
            name="hidden_regression", files=read_tree(root / "hidden" / "regression"),
            command=GROUP_COMMANDS["hidden_regression"],
        ),
        WorkflowTestGroup(
            name="new_behavior", files=read_tree(root / "hidden" / "new_behavior"),
            command=GROUP_COMMANDS["new_behavior"],
        ),
    )
    return SmokeEditFixture(
        repository=repository,
        task=(root / "task.md").read_text(encoding="utf-8"),
        groups=groups,
        reference_patch=(root / "patches" / "reference.patch").read_text(encoding="utf-8"),
        negative_patch=(root / "patches" / "negative.patch").read_text(encoding="utf-8"),
    )
