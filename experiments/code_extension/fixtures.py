"""Load a sidecar-backed extension scenario without exposing operator assets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from assay.canonical import digest_bytes
from assay.investigations.workflow_correctness import WorkflowTestGroup, workflow_tree_digest
from assay.models import NonEmpty, Sha256Ref, WireModel
from code_extension.contract import ExtensionScenarioSidecar as BaseSidecar
from code_extension.fixture import PILOT, frozen_groups, read_tree


class NegativeExpectation(WireModel):
    """Declared failure and the expected result of every other group."""

    patch_name: NonEmpty
    intent: NonEmpty
    intended_group: Literal["visible_regression", "hidden_regression", "new_behavior"]
    unrelated_results: dict[str, Literal["passed", "failed"]]

    @model_validator(mode="after")
    def complete(self) -> Self:
        groups = {"visible_regression", "hidden_regression", "new_behavior"}
        if set(self.unrelated_results) != groups - {self.intended_group}:
            raise ValueError("negative patch must document every unrelated group")
        return self


class FixtureProvenance(WireModel):
    extraction_invocation: NonEmpty
    extraction_rules: tuple[NonEmpty, ...] = Field(min_length=1)
    licenses: tuple[NonEmpty, ...] = Field(min_length=1)
    local_adaptations: tuple[NonEmpty, ...] = Field(min_length=1)
    start_tree_digest: Sha256Ref
    start_file_count: int = Field(ge=1, le=200)
    start_total_bytes: int = Field(ge=1, le=1_000_000)
    dependency_lock_digests: dict[str, Sha256Ref]


class ExtensionScenarioSidecar(BaseSidecar):
    """The existing 0.1.0 sidecar contract plus WP1 scenario details."""

    tool_instructions: NonEmpty
    negative_expectations: tuple[NegativeExpectation, ...] = Field(min_length=2)
    provenance: FixtureProvenance


@dataclass(frozen=True, slots=True)
class ScenarioArm:
    arm_id: str
    reference_patch: str
    negative_patches: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScenarioFixture:
    subject_id: str
    repository: dict[str, str]
    task: str
    groups: tuple[WorkflowTestGroup, WorkflowTestGroup, WorkflowTestGroup]
    arms: tuple[ScenarioArm, ...]
    sidecar: ExtensionScenarioSidecar

    @property
    def tree_digest(self) -> str:
        return workflow_tree_digest(self.repository)


def touched_paths(patch: str) -> tuple[str, ...]:
    paths: set[str] = set()
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) != 4 or not parts[2].startswith("a/") or not parts[3].startswith("b/"):
                raise ValueError("invalid patch diff header")
            paths.update((parts[2][2:], parts[3][2:]))
    if not paths:
        raise ValueError("patch has no diff headers")
    return tuple(sorted(paths))


def sidecar_for_subject(subject_id: str) -> ExtensionScenarioSidecar | None:
    """Resolve a committed scenario's scope by subject, refusing duplicate records."""
    matches = []
    for path in sorted(PILOT.parent.glob("*/qualification/sidecar.json")):
        sidecar = ExtensionScenarioSidecar.model_validate_json(path.read_bytes())
        if sidecar.subject_id == subject_id:
            matches.append(sidecar)
    if len(matches) > 1:
        raise ValueError(f"duplicate sidecars for extension subject {subject_id}")
    return matches[0] if matches else None


def load_scenario(name: str, root: Path | None = None) -> ScenarioFixture:
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError("invalid scenario key")
    directory = root or PILOT.parent / name
    sidecar = ExtensionScenarioSidecar.model_validate_json(
        (directory / "qualification" / "sidecar.json").read_bytes()
    )
    repository = read_tree(directory / "repository")
    groups = frozen_groups(repository, directory)
    task = (directory / "task.md").read_text(encoding="utf-8")
    if sidecar.provenance.start_tree_digest != workflow_tree_digest(repository):
        raise ValueError("sidecar start tree digest differs from repository")
    if sidecar.provenance.start_file_count != len(
        repository
    ) or sidecar.provenance.start_total_bytes != sum(
        len(value.encode()) for value in repository.values()
    ):
        raise ValueError("sidecar tree size differs from repository")
    for lock, digest in sidecar.provenance.dependency_lock_digests.items():
        if lock not in repository or digest_bytes(repository[lock].encode()) != digest:
            raise ValueError("sidecar dependency lock digest differs")
    patches = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted((directory / "patches").glob("*.patch"))
    }
    inventory = {item.digest: item for item in sidecar.patch_inventory}
    for patch in patches.values():
        digest = digest_bytes(patch.encode())
        declared = inventory.get(digest)
        if declared is None or touched_paths(patch) != declared.touched_paths:
            raise ValueError("patch inventory differs from actual diff headers")
        if any(
            path in sidecar.protected_assets.paths
            or not any(
                path.startswith(prefix.rstrip("/") + "/") or path == prefix.rstrip("/")
                for prefix in sidecar.writable_implementation_scope
            )
            for path in touched_paths(patch)
        ):
            raise ValueError("patch touches path outside writable prefixes or protected file")
    if len(patches) != len(inventory) or "reference.patch" not in patches:
        raise ValueError("patch inventory is incomplete")
    negatives = tuple(patches[item.patch_name] for item in sidecar.negative_expectations)
    if len(set(negatives)) != len(negatives):
        raise ValueError("negative patches must be distinct")
    return ScenarioFixture(
        subject_id=sidecar.subject_id,
        repository=repository,
        task=task,
        groups=groups,
        arms=(ScenarioArm("baseline", patches["reference.patch"], negatives),),
        sidecar=sidecar,
    )
