"""Versioned study sidecar for contracts absent from fixture manifest 0.3.0."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from assay.models import Identifier, NonEmpty, Sha256Ref, WireModel

SIDECAR_SCHEMA_VERSION: Literal["assay-extension-scenario-sidecar/0.1.0"] = (
    "assay-extension-scenario-sidecar/0.1.0"
)


def _path_in_scope(path: str, scope: str) -> bool:
    return path == scope.rstrip("/") or path.startswith(scope.rstrip("/") + "/")


def _canonical_relative_path(path: str, *, scope: bool = False) -> bool:
    """Accept only repository-relative POSIX paths with no traversal segments."""
    if path.startswith("/") or "\\" in path or ":" in path:
        return False
    if scope:
        path = path.removesuffix("/")
    return bool(path) and all(part not in ("", ".", "..") for part in path.split("/"))


class ProtectedAssets(WireModel):
    """Explicit paths excluded from candidate writes and available to qualification."""

    test_files: tuple[NonEmpty, ...]
    dependency_files: tuple[NonEmpty, ...]
    configuration_files: tuple[NonEmpty, ...]

    @field_validator("test_files", "dependency_files", "configuration_files")
    @classmethod
    def valid_paths(cls, paths: tuple[str, ...]) -> tuple[str, ...]:
        if any(not _canonical_relative_path(path) for path in paths):
            raise ValueError("protected assets must use canonical relative file paths")
        return paths

    @property
    def paths(self) -> tuple[str, ...]:
        return (*self.test_files, *self.dependency_files, *self.configuration_files)


class TestAssertion(WireModel):
    """One assertion in a named visible or hidden test group."""

    assertion_id: Identifier
    group_name: Identifier
    visibility: Literal["visible", "hidden"]


class RequirementTestLink(WireModel):
    """A test assertion's public requirement or documented existing behavior."""

    assertion_id: Identifier
    citation_kind: Literal["public_requirement", "preexisting_behavior"]
    citation: NonEmpty


class PatchInventoryItem(WireModel):
    """A held patch's intent and the implementation paths it touches."""

    arm_id: Identifier
    kind: Literal["reference", "incomplete"]
    digest: Sha256Ref
    intent: NonEmpty
    touched_paths: tuple[NonEmpty, ...] = Field(min_length=1)

    @field_validator("touched_paths")
    @classmethod
    def valid_touched_paths(cls, paths: tuple[str, ...]) -> tuple[str, ...]:
        if any(not _canonical_relative_path(path) for path in paths):
            raise ValueError("patch touched paths must use canonical relative file paths")
        return paths


class QualificationEvidenceRefs(WireModel):
    """Content-addressed evidence for the five additional qualification checks."""

    leak_scan: Sha256Ref
    access_probe: Sha256Ref
    no_op: Sha256Ref
    scripted_submission: Sha256Ref
    double_reproduction: Sha256Ref


class ExtensionScenarioSidecar(WireModel):
    """Scenario-specific scope, oracle mapping, held patches and evidence refs."""

    schema_version: Literal["assay-extension-scenario-sidecar/0.1.0"] = (
        SIDECAR_SCHEMA_VERSION
    )
    subject_id: Identifier
    writable_implementation_scope: tuple[NonEmpty, ...] = Field(min_length=1)
    protected_assets: ProtectedAssets
    public_requirements: tuple[NonEmpty, ...] = Field(min_length=1)
    preexisting_behaviors: tuple[NonEmpty, ...]
    test_assertions: tuple[TestAssertion, ...] = Field(min_length=1)
    requirements_to_tests: tuple[RequirementTestLink, ...] = Field(min_length=1)
    patch_inventory: tuple[PatchInventoryItem, ...] = Field(min_length=1)
    evidence: QualificationEvidenceRefs

    @field_validator("writable_implementation_scope")
    @classmethod
    def valid_scope(cls, scopes: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(scopes)) != len(scopes) or any(
            not _canonical_relative_path(path, scope=True)
            for path in scopes
        ):
            raise ValueError("writable scope must use unique canonical relative paths")
        return scopes

    @model_validator(mode="after")
    def consistent(self) -> Self:
        scopes = self.writable_implementation_scope
        for patch in self.patch_inventory:
            if any(not any(_path_in_scope(path, scope) for scope in scopes)
                   for path in patch.touched_paths):
                raise ValueError(
                    "reference or incomplete patch touches path outside writable scope"
                )
        if any(any(_path_in_scope(path, scope) or _path_in_scope(scope, path)
                   for scope in scopes) for path in self.protected_assets.paths):
            raise ValueError("protected assets overlap writable scope")
        assertions = {item.assertion_id: item for item in self.test_assertions}
        if len(assertions) != len(self.test_assertions):
            raise ValueError("test assertion ids must be unique")
        linked = {link.assertion_id for link in self.requirements_to_tests}
        if any(item.visibility == "hidden" and item.assertion_id not in linked
               for item in self.test_assertions):
            raise ValueError("hidden assertion is unlinked in requirements-to-tests table")
        if linked - assertions.keys():
            raise ValueError("requirements-to-tests table names an undeclared assertion")
        for link in self.requirements_to_tests:
            declared = (self.public_requirements if link.citation_kind == "public_requirement"
                        else self.preexisting_behaviors)
            if link.citation not in declared:
                raise ValueError("requirements-to-tests table has dangling citation")
        return self
