"""Grade each extension cell against its own arm and frozen scenario checks."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field

from workflow_edit.evaluation import cell_arm, unavailable_result, worker_candidate

from assay.execution import EvaluationFailed, EvaluationResult, EvaluationSuccess
from assay.fixture_manifest import FixtureManifestV3, fixture_identity
from assay.investigations.workflow_correctness import (
    DockerWorkflowRunner,
    WorkflowCorrectnessResult,
    WorkflowTestGroup,
    workflow_tree_digest,
)
from assay.models import EvaluationCoordinate
from assay.pier_protocol import CandidateSubmission
from assay.store import ObjectIntegrityError, ObjectStore

STUDY_GROUPS = (("visible_regression", False), ("hidden_regression", True), ("new_behavior", True))
CORRECTNESS_CATEGORIES = ("correct", "incorrect", "unavailable")


async def evaluate_scenario_candidate(
    *,
    store: ObjectStore,
    manifest: FixtureManifestV3,
    subject_id: str,
    arm_id: str,
    baseline: Mapping[str, str],
    submission: CandidateSubmission,
    runner: DockerWorkflowRunner,
) -> WorkflowCorrectnessResult:
    """Use the coordinate's arm, realization tree, and worker-reported baseline digest."""
    scenario = manifest.scenario(subject_id)
    if scenario is None:
        return unavailable_result("unknown_subject")
    arm = next((item for item in scenario.arms if item.arm_id == arm_id), None)
    if arm is None or arm_id not in manifest.arm_set.arm_ids:
        return unavailable_result("unknown_arm")
    if workflow_tree_digest(baseline) != arm.tree_digest:
        return unavailable_result("realization_digest_mismatch")
    if submission.baseline_tree_digest != arm.tree_digest:
        return unavailable_result("baseline_digest_mismatch")
    if runner.settings.image != manifest.observed_runtime_image_digest:
        return unavailable_result("image_digest_mismatch")
    refs = [
        next(
            (group for group in (scenario.hidden_tests if hidden else scenario.visible_tests)
             if group.name == name),
            None,
        )
        for name, hidden in STUDY_GROUPS
    ]
    if any(ref is None for ref in refs):
        return unavailable_result("missing_test_group")
    try:
        groups = tuple(
            WorkflowTestGroup.model_validate_json(store.read_bytes(ref.digest))
            for ref in refs if ref is not None
        )
        patch = store.read_bytes(submission.patch_ref).decode("utf-8")
    except (OSError, UnicodeError, ValueError, ObjectIntegrityError):
        return unavailable_result("fixture_asset_unavailable")
    if [group.name for group in groups] != [name for name, _ in STUDY_GROUPS] or [
        group.restores for group in groups
    ] != [not hidden for _, hidden in STUDY_GROUPS]:
        return unavailable_result("invalid_test_groups")
    return await runner.run(
        baseline=baseline,
        baseline_tree_digest=arm.tree_digest,
        expected_tree_digest=submission.tree_digest,
        patch=patch,
        groups=groups,
    )


@dataclass
class CellEvaluator:
    store: ObjectStore
    manifest: FixtureManifestV3
    runner: DockerWorkflowRunner
    records: dict[str, dict[str, object]] = field(default_factory=dict)

    def configuration(self) -> dict[str, object]:
        return {
            "id": "code-extension-correctness",
            "version": "1",
            "categories": list(CORRECTNESS_CATEGORIES),
            "runner": self.runner.configuration(),
            "fixture": fixture_identity(self.manifest),
        }

    async def evaluate(
        self, *, input_value: object, output: object, coordinate: EvaluationCoordinate
    ) -> EvaluationResult:
        started = time.monotonic()
        subject_id, arm_id = cell_arm(coordinate)
        try:
            if not isinstance(output, Mapping) or output.get("cell_id") != coordinate.cell_id:
                return EvaluationFailed("MismatchedCell", "output belongs to another cell")
            candidate = worker_candidate(self.store, output)
            if not isinstance(input_value, Mapping):
                raise ValueError("missing realization")
            baseline = input_value.get("repository")
            if not isinstance(baseline, Mapping) or not all(
                isinstance(path, str) and isinstance(source, str)
                for path, source in baseline.items()
            ):
                raise ValueError("invalid realization")
        except (KeyError, TypeError, ValueError, ObjectIntegrityError, OSError) as error:
            return EvaluationFailed("MissingCandidate", f"unreadable candidate: {error}")
        submission = CandidateSubmission(
            patch_ref=str(self.store.publish_bytes(candidate.patch)),
            tree_digest=candidate.tree_digest,
            baseline_tree_digest=candidate.baseline_tree_digest,
        )
        result = await evaluate_scenario_candidate(
            store=self.store,
            manifest=self.manifest,
            subject_id=subject_id,
            arm_id=arm_id,
            baseline=baseline,
            submission=submission,
            runner=self.runner,
        )
        groups = {
            group.name: {"status": group.status, "cause": group.cause} for group in result.groups
        }
        self.records[coordinate.cell_id] = {
            "verdict": result.verdict,
            "cause": result.cause,
            "groups": groups,
            "empty_patch": candidate.patch == b"",
            "seconds": round(time.monotonic() - started, 3),
        }
        return EvaluationSuccess(
            result.verdict,
            (result.cause,) if result.cause else (),
            {"groups": groups, "empty_patch": candidate.patch == b""},
        )
