"""Load the committed pilot repository, task, frozen groups, and private patches."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from assay.investigations.workflow_correctness import WorkflowTestGroup, workflow_tree_digest
from assay.repository import validate_repository

PILOT = Path(__file__).resolve().parent / "fixtures" / "pilot"
SUBJECT_ID = "oakridge-dbos-context-defaults"
CHECKPOINT_SHA = "f3b3ffca43e43672ff2f58ab797d65c7532aaed8"
MAX_REPOSITORY_FILES = 200
MAX_REPOSITORY_BYTES = 1_000_000
VISIBLE_PREFIX = "tests/visible/"


def read_tree(root: Path) -> dict[str, str]:
    if not root.is_dir():
        raise ValueError(f"missing fixture tree: {root}")
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"fixture symlink is not allowed: {path}")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8")
    return validate_repository(
        files, max_files=MAX_REPOSITORY_FILES, max_total_bytes=MAX_REPOSITORY_BYTES
    )


def materialize(root: Path, repository: Mapping[str, str], patch: str = "") -> None:
    for name, source in repository.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    if patch:
        subprocess.run(
            ["git", "apply", "--allow-empty", "-"],
            cwd=root,
            input=patch.encode("utf-8"),
            check=True,
            capture_output=True,
        )


@dataclass(frozen=True, slots=True)
class PilotArm:
    arm_id: str
    reference_patch: str
    negative_patches: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PilotFixture:
    repository: dict[str, str]
    task: str
    groups: tuple[WorkflowTestGroup, WorkflowTestGroup, WorkflowTestGroup]
    arms: tuple[PilotArm, ...]

    @property
    def tree_digest(self) -> str:
        return workflow_tree_digest(self.repository)


def load_fixture(root: Path = PILOT) -> PilotFixture:
    repository = read_tree(root / "repository")
    visible = {
        name: source for name, source in repository.items() if name.startswith(VISIBLE_PREFIX)
    }
    if not visible or any(name.startswith("tests/hidden/") for name in repository):
        raise ValueError("pilot repository must contain visible tests and no hidden tests")
    hidden_regression = read_tree(root / "hidden" / "regression")
    new_behavior = read_tree(root / "hidden" / "new_behavior")
    if set(repository) & (set(hidden_regression) | set(new_behavior)):
        raise ValueError("hidden tests collide with the shipped repository")
    groups = (
        WorkflowTestGroup(
            name="visible_regression",
            files=visible,
            command=(
                "bun",
                "test",
                *sorted("./" + name for name in visible if name.endswith(".test.ts")),
            ),
            restores=True,
        ),
        WorkflowTestGroup(
            name="hidden_regression",
            files=hidden_regression,
            command=("bun", "test", "./tests/hidden/regression"),
        ),
        WorkflowTestGroup(
            name="new_behavior",
            files=new_behavior,
            command=("bun", "test", "./tests/hidden/new-behavior"),
        ),
    )
    arm = PilotArm(
        arm_id="baseline",
        reference_patch=(root / "patches" / "reference.patch").read_text(encoding="utf-8"),
        negative_patches=((root / "patches" / "negative.patch").read_text(encoding="utf-8"),),
    )
    return PilotFixture(
        repository=repository,
        task=(root / "task.md").read_text(encoding="utf-8"),
        groups=groups,
        arms=(arm,),
    )


ADDED_SCENARIOS = {
    "pointer-root": ("oakridge-dbos-pointer-root", ("baseline",)),
    "stage-pass-through": (
        "oakridge-dbos-stage-pass-through",
        ("modular", "central", "cross_module", "plugin"),
    ),
}


@dataclass(frozen=True, slots=True)
class CommittedArm:
    arm_id: str
    repository: dict[str, str]
    reference_patch: str
    negative_patch: str


@dataclass(frozen=True, slots=True)
class CommittedScenario:
    subject_id: str
    task: str
    groups: tuple[WorkflowTestGroup, WorkflowTestGroup, WorkflowTestGroup]
    arms: tuple[CommittedArm, ...]


def load_committed_scenario(name: str) -> CommittedScenario:
    """Read one added scenario using the pilot's frozen group construction."""
    if name not in ADDED_SCENARIOS:
        raise ValueError(f"unknown extension scenario: {name}")
    subject_id, arm_ids = ADDED_SCENARIOS[name]
    root = PILOT.parent / name
    arms: list[CommittedArm] = []
    for arm_id in arm_ids:
        tree = root / "repository" / arm_id if len(arm_ids) > 1 else root / "repository"
        repository = read_tree(tree)
        suffix = f"{arm_id}." if len(arm_ids) > 1 else ""
        arms.append(
            CommittedArm(
                arm_id=arm_id,
                repository=repository,
                reference_patch=(root / "patches" / f"{suffix}reference.patch").read_text(),
                negative_patch=(root / "patches" / f"{suffix}negative.patch").read_text(),
            )
        )
    first = arms[0].repository
    visible = {path: source for path, source in first.items() if path.startswith(VISIBLE_PREFIX)}
    if not visible:
        raise ValueError(f"scenario {name} has no visible tests")
    hidden_regression = read_tree(root / "hidden" / "regression")
    new_behavior = read_tree(root / "hidden" / "new_behavior")
    if set(first) & (set(hidden_regression) | set(new_behavior)):
        raise ValueError(f"scenario {name} ships a hidden check path")
    groups = (
        WorkflowTestGroup(
            name="visible_regression",
            files=visible,
            command=(
                "bun",
                "test",
                *sorted("./" + path for path in visible if path.endswith(".test.ts")),
            ),
            restores=True,
        ),
        WorkflowTestGroup(
            name="hidden_regression",
            files=hidden_regression,
            command=("bun", "test", "./tests/hidden/regression"),
        ),
        WorkflowTestGroup(
            name="new_behavior",
            files=new_behavior,
            command=("bun", "test", "./tests/hidden/new-behavior"),
        ),
    )
    return CommittedScenario(
        subject_id=subject_id,
        task=(root / "task.md").read_text(),
        groups=groups,
        arms=tuple(arms),
    )
