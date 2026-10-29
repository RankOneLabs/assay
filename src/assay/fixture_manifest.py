"""Versioned identity of a workflow fixture and its operator-held assets.

``assay-fixture-manifest/0.1.0`` describes one single-arm fixture and stays
readable unchanged. ``assay-fixture-manifest/0.2.0`` describes one checkpoint
and a tuple of task records, one per subject, each carrying its four dose arms.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Annotated, Any, Literal, Self, get_args

from pydantic import Field, StringConstraints, TypeAdapter, field_validator, model_validator

from assay.canonical import canonical_json, digest_bytes
from assay.models import Identifier, NonEmpty, Sha256Ref, WireModel

CheckpointSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]


class TreatmentSite(WireModel):
    """A path and description of one intentional treatment location."""

    path: NonEmpty
    description: NonEmpty


class FixtureManifest(WireModel):
    """All identity-bearing inputs of a fixture, with hidden assets by digest only.

    ``observed_runtime_image_digest`` is the digest inspected from the built
    image, not a value declared before the build. Hidden tests, patches, and
    rubric cannot be inlined in this closed wire shape.
    """

    schema_version: Literal["assay-fixture-manifest/0.1.0"]
    checkpoint_sha: CheckpointSha
    included_paths: tuple[str, ...]
    excluded_paths: tuple[str, ...]
    dependency_lock_digests: dict[str, Sha256Ref]
    observed_runtime_image_digest: Sha256Ref
    normalization_diff: str
    treatment_site_inventory: tuple[TreatmentSite, ...]
    per_arm_tree_digests: dict[Identifier, Sha256Ref] = Field(
        json_schema_extra={"additionalProperties": False}
    )
    transformation_version: NonEmpty
    equivalence_test_version: NonEmpty
    task_prompt: NonEmpty
    hidden_tests: tuple[Sha256Ref, ...] = Field(min_length=1)
    reference_patch: Sha256Ref
    negative_patches: tuple[Sha256Ref, ...] = Field(min_length=1)
    rubric: Sha256Ref
    routing_config_digest: Sha256Ref


# --- assay-fixture-manifest/0.2.0 -------------------------------------------

DosedArm = Literal["mess-low", "mess-mid", "mess-high"]
DoseArm = Literal["mess-00", DosedArm]
# Dose order, not identifier order: each arm's inline sites contain the previous arm's.
DOSED_ARMS: tuple[DosedArm, ...] = get_args(DosedArm)
DOSE_ARMS: tuple[DoseArm, ...] = ("mess-00", *DOSED_ARMS)
QualificationOutcome = Literal["passed", "failed", "unavailable"]


def dose_count(arm: DoseArm, n: int) -> int:
    """Inline sites in ``arm`` for N eligible sites: 0, 1, ceil(N/2), N."""
    return {"mess-00": 0, "mess-low": 1, "mess-mid": math.ceil(n / 2), "mess-high": n}[arm]


def _relative_path(value: str) -> str:
    parts = value.split("/")
    if value.startswith("/") or any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"path must be a normalized relative POSIX path: {value!r}")
    return value


def _require_nested(arms: tuple[DosedArm, ...], what: str) -> None:
    """``arms`` must be a dose-ordered suffix: what a dose contains, every larger dose contains."""
    if list(arms) != sorted(set(arms), key=DOSED_ARMS.index):
        raise ValueError(f"{what} must be unique and listed in dose order")
    if arms and arms != DOSED_ARMS[DOSED_ARMS.index(arms[0]) :]:
        raise ValueError(
            f"{what} must nest: mess-low ⊂ mess-mid ⊂ mess-high, got {list(arms)}"
        )


class LineSpan(WireModel):
    """1-based, inclusive line range in the ``mess-00`` tree."""

    start_line: int = Field(ge=1, strict=True)
    end_line: int = Field(ge=1, strict=True)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end_line < self.start_line:
            raise ValueError("end_line must not precede start_line")
        return self

    def overlaps(self, other: LineSpan) -> bool:
        return self.start_line <= other.end_line and other.start_line <= self.end_line


class RemovedImport(WireModel):
    """An import the treatment removes from the site's file in the listed arms.

    An import shared by several sites in one file is removed only once all of
    them are inline, so it is attributed to the site whose dosing removes it,
    with exactly the arms where it is gone.
    """

    module: NonEmpty
    name: NonEmpty
    arms: tuple[DosedArm, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def nested(self) -> Self:
        _require_nested(self.arms, "removed-import arms")
        return self


class CommentCorrection(WireModel):
    """A mechanically necessary comment edit in the site's file, wherever the site is dosed."""

    span: LineSpan
    reason: NonEmpty


class DoseSite(WireModel):
    """One treatment unit: a calling function whose delegation becomes an inline copy."""

    rank: int = Field(ge=1, strict=True, description="Dose order; mess-low doses rank 1.")
    path: NonEmpty
    symbol: NonEmpty = Field(description="The calling function that is the treatment unit.")
    span: LineSpan
    arms: tuple[DosedArm, ...] = Field(
        min_length=1, description="Dose membership: every arm in which this site is inline."
    )
    removed_imports: tuple[RemovedImport, ...] = ()
    comment_corrections: tuple[CommentCorrection, ...] = ()

    @field_validator("path")
    @classmethod
    def relative(cls, value: str) -> str:
        return _relative_path(value)

    @model_validator(mode="after")
    def membership(self) -> Self:
        _require_nested(self.arms, "dose membership")
        for removed in self.removed_imports:
            if not set(removed.arms) <= set(self.arms):
                raise ValueError("an import can be removed only in arms where its site is inline")
        return self


class NamedTestGroup(WireModel):
    """A frozen test group by name and the digest of its stored group object."""

    name: Identifier
    digest: Sha256Ref


class QualificationResult(WireModel):
    """One observed qualification run and the digest of its retained record."""

    outcome: QualificationOutcome
    evidence: Sha256Ref


class ArmQualification(WireModel):
    """The four section-6 checks on one arm; each field name states its expected outcome."""

    baseline_passes: QualificationResult
    feature_fails: QualificationResult
    reference_passes: QualificationResult
    equivalence_passes: QualificationResult

    @property
    def qualified(self) -> bool:
        return (
            self.baseline_passes.outcome == "passed"
            and self.feature_fails.outcome == "failed"
            and self.reference_passes.outcome == "passed"
            and self.equivalence_passes.outcome == "passed"
        )


class ArmFixture(WireModel):
    """One arm's realization and its per-arm hidden assets, by digest only."""

    tree_digest: Sha256Ref
    reference_patch: Sha256Ref
    negative_patches: tuple[Sha256Ref, ...] = Field(min_length=1)
    qualification: ArmQualification

    @field_validator("negative_patches")
    @classmethod
    def unique_negatives(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("negative patches must be distinct")
        return value


class FixtureTask(WireModel):
    """The task record of one subject: its prompt, dose inventory, arms and oracles."""

    subject_id: Identifier
    task_prompt: NonEmpty = Field(description="Byte-identical across the four arms.")
    normalization_patch: Sha256Ref = Field(
        description="Consolidation from the checkpoint slice to the mess-00 reference."
    )
    transformation_version: NonEmpty
    treatment_site_count: int = Field(ge=4, strict=True, description="N, the eligible sites.")
    treatment_sites: tuple[DoseSite, ...]
    arms: dict[DoseArm, ArmFixture] = Field(min_length=len(DOSE_ARMS))
    visible_tests: tuple[NamedTestGroup, ...] = Field(min_length=1)
    hidden_tests: tuple[NamedTestGroup, ...] = Field(min_length=1)
    equivalence_suite: Sha256Ref
    rubric: Sha256Ref

    @model_validator(mode="after")
    def consistent(self) -> Self:
        n = self.treatment_site_count
        sites = self.treatment_sites
        if len(sites) != n:
            raise ValueError(f"treatment_site_count is {n} but {len(sites)} sites are listed")
        if [site.rank for site in sites] != list(range(1, n + 1)):
            raise ValueError("site ranks must be 1..N, listed in rank order")
        for arm in DOSED_ARMS:
            ranks = [site.rank for site in sites if arm in site.arms]
            expected = dose_count(arm, n)
            if len(ranks) != expected:
                raise ValueError(f"{arm} must dose {expected} of N={n} sites, got {len(ranks)}")
            if ranks != list(range(1, expected + 1)):
                raise ValueError(f"{arm} must dose the {expected} lowest-ranked sites")
        _require_disjoint_sites(sites)
        if set(self.arms) != set(DOSE_ARMS):
            raise ValueError("arms must be exactly the four dose arms")
        if len({arm.tree_digest for arm in self.arms.values()}) != len(DOSE_ARMS):
            raise ValueError("every arm must have its own repository tree")
        groups = (*self.visible_tests, *self.hidden_tests)
        if len({group.name for group in groups}) != len(groups):
            raise ValueError("test group names must be unique across visible and hidden groups")
        if len({group.digest for group in groups}) != len(groups):
            raise ValueError("test group digests must be distinct")
        return self

    def group(self, name: str, *, hidden: bool) -> NamedTestGroup | None:
        groups = self.hidden_tests if hidden else self.visible_tests
        return next((group for group in groups if group.name == name), None)

    @property
    def qualified(self) -> bool:
        return all(arm.qualification.qualified for arm in self.arms.values())


def _require_disjoint_sites(sites: Iterable[DoseSite]) -> None:
    seen: list[DoseSite] = []
    for site in sites:
        for other in seen:
            if site.path == other.path and (
                site.symbol == other.symbol or site.span.overlaps(other.span)
            ):
                raise ValueError(f"sites overlap in {site.path}: {other.symbol}, {site.symbol}")
        seen.append(site)


class FixtureManifestV2(WireModel):
    """One checkpoint-level fixture and a task record per subject, hidden assets by digest.

    ``routing_config_digest`` is required but nullable: a local fixture binds
    its Smithers routing digest, and a hosted fixture states ``null`` rather
    than omitting it.
    """

    schema_version: Literal["assay-fixture-manifest/0.2.0"]
    checkpoint_sha: CheckpointSha
    included_paths: tuple[str, ...]
    excluded_paths: tuple[str, ...]
    normalization_diff: str
    dependency_lock_digests: dict[str, Sha256Ref]
    observed_runtime_image_digest: Sha256Ref
    routing_config_digest: Sha256Ref | None
    tasks: tuple[FixtureTask, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def ordered_tasks(self) -> Self:
        ids = [task.subject_id for task in self.tasks]
        if ids != sorted(set(ids)):
            raise ValueError("tasks must have unique subject ids, listed in sorted order")
        return self

    def task(self, subject_id: str) -> FixtureTask | None:
        return next((task for task in self.tasks if task.subject_id == subject_id), None)


# --- assay-fixture-manifest/0.3.0 -------------------------------------------


class _ExtensionArmSet(WireModel):
    arm_ids: tuple[Identifier, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def unique_arms(self) -> Self:
        if len(set(self.arm_ids)) != len(self.arm_ids):
            raise ValueError("arm ids must be unique")
        return self


class CodeShapeArmSet(_ExtensionArmSet):
    factor: Literal["code_shape"]


class HandoffDetailArmSet(_ExtensionArmSet):
    factor: Literal["handoff_detail"]


class ModelProfileArmSet(_ExtensionArmSet):
    factor: Literal["model_profile"]


class CodeIntelligenceModeArmSet(_ExtensionArmSet):
    factor: Literal["code_intelligence_mode"]


class BaselineArmSet(WireModel):
    factor: Literal["baseline"]
    arm_ids: tuple[Literal["baseline"]]


ExtensionArmSet = Annotated[
    CodeShapeArmSet
    | HandoffDetailArmSet
    | ModelProfileArmSet
    | CodeIntelligenceModeArmSet
    | BaselineArmSet,
    Field(discriminator="factor"),
]


class ExtensionArmQualification(WireModel):
    """The three retained qualification outcomes for one extension arm."""

    baseline_passes: QualificationResult
    feature_fails: QualificationResult
    reference_passes: QualificationResult

    @property
    def qualified(self) -> bool:
        return (
            self.baseline_passes.outcome == "passed"
            and self.feature_fails.outcome == "failed"
            and self.reference_passes.outcome == "passed"
        )


class ExtensionArmRealization(WireModel):
    """One arm's tree, prompt and private qualification assets by digest."""

    arm_id: Identifier
    tree_digest: Sha256Ref
    task_prompt: NonEmpty
    reference_patch: Sha256Ref
    negative_patches: tuple[Sha256Ref, ...] = Field(min_length=1)
    qualification: ExtensionArmQualification

    @field_validator("negative_patches")
    @classmethod
    def unique_negatives(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("negative patches must be distinct")
        return value


class ExtensionScenario(WireModel):
    """A pinned checkpoint slice and one bounded feature request."""

    subject_id: Identifier
    checkpoint_sha: CheckpointSha
    included_paths: tuple[str, ...] = Field(min_length=1)
    excluded_paths: tuple[str, ...]
    dependency_lock_digests: dict[str, Sha256Ref]
    feature_request: NonEmpty
    visible_requirements: tuple[NonEmpty, ...] = Field(min_length=1)
    visible_tests: tuple[NamedTestGroup, ...] = Field(min_length=1)
    hidden_tests: tuple[NamedTestGroup, ...] = Field(min_length=1)
    arms: tuple[ExtensionArmRealization, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_groups(self) -> Self:
        groups = (*self.visible_tests, *self.hidden_tests)
        if len({group.name for group in groups}) != len(groups):
            raise ValueError("test group names must be unique across visible and hidden groups")
        if len({group.digest for group in groups}) != len(groups):
            raise ValueError("test group digests must be distinct")
        return self

    @property
    def qualified(self) -> bool:
        return all(arm.qualification.qualified for arm in self.arms)

    def require_qualified(self) -> None:
        """Refuse this subject before planning if any arm missed its gate."""
        if not self.qualified:
            raise ValueError(f"scenario {self.subject_id} has an unqualified arm")


class FixtureManifestV3(WireModel):
    """One factor's extension subjects, with all private assets by digest."""

    schema_version: Literal["assay-fixture-manifest/0.3.0"]
    arm_set: ExtensionArmSet
    observed_runtime_image_digest: Sha256Ref
    routing_config_digest: Sha256Ref | None
    scenarios: tuple[ExtensionScenario, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        ids = [scenario.subject_id for scenario in self.scenarios]
        if ids != sorted(set(ids)):
            raise ValueError("scenarios must have unique subject ids, listed in sorted order")
        expected = set(self.arm_set.arm_ids)
        for scenario in self.scenarios:
            arms = scenario.arms
            if len(arms) != len(expected) or {arm.arm_id for arm in arms} != expected:
                raise ValueError(
                    f"scenario {scenario.subject_id} must have exactly the declared arms"
                )
            trees = {arm.tree_digest for arm in arms}
            if self.arm_set.factor == "code_shape":
                if len(trees) != len(arms):
                    raise ValueError("code_shape arms must have distinct repository trees")
            elif len(trees) != 1:
                raise ValueError(f"{self.arm_set.factor} arms must share one repository tree")
            if (
                self.arm_set.factor != "handoff_detail"
                and len({arm.task_prompt for arm in arms}) != 1
            ):
                raise ValueError(
                    f"{self.arm_set.factor} arms must have byte-identical task prompts"
                )
        return self

    @property
    def qualified(self) -> bool:
        return all(scenario.qualified for scenario in self.scenarios)

    def require_qualified(self) -> None:
        """Refuse planning while any subject has an unqualified arm."""
        for scenario in self.scenarios:
            scenario.require_qualified()

    def scenario(self, subject_id: str) -> ExtensionScenario | None:
        return next((item for item in self.scenarios if item.subject_id == subject_id), None)


AnyFixtureManifest = Annotated[
    FixtureManifest | FixtureManifestV2 | FixtureManifestV3, Field(discriminator="schema_version")
]
_manifest_adapter: TypeAdapter[FixtureManifest | FixtureManifestV2 | FixtureManifestV3] = (
    TypeAdapter(AnyFixtureManifest)
)


def parse_fixture_manifest(value: Any) -> FixtureManifest | FixtureManifestV2 | FixtureManifestV3:
    """Select the manifest model from ``schema_version``; an unknown version is rejected."""
    return _manifest_adapter.validate_python(value)


def fixture_identity(manifest: FixtureManifest | FixtureManifestV2 | FixtureManifestV3) -> str:
    """Digest the complete canonical manifest, including image and routing."""
    return digest_bytes(canonical_json(manifest.model_dump(mode="json")))


def task_record_digest(task: FixtureTask) -> str:
    """Digest one subject's task record, for binding into that subject's payload."""
    return digest_bytes(canonical_json(task.model_dump(mode="json")))
