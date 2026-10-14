"""Bind workflow correctness inputs to the frozen fixture and object store."""

from __future__ import annotations

from collections.abc import Mapping

from assay.fixture_manifest import FixtureManifest
from assay.investigations.workflow_correctness import (
    DockerWorkflowRunner,
    GroupResult,
    WorkflowCorrectnessResult,
    WorkflowTestGroup,
)
from assay.pier_protocol import CandidateSubmission
from assay.store import ObjectIntegrityError, ObjectStore
from workflow_edit.arms import ARM_IDS


async def evaluate_candidate(
    *,
    store: ObjectStore,
    fixture: FixtureManifest,
    arm_id: str,
    baseline: Mapping[str, str],
    submission: CandidateSubmission,
    visible_regression: WorkflowTestGroup,
    hidden_regression_ref: str,
    new_behavior_ref: str,
    runner: DockerWorkflowRunner,
) -> WorkflowCorrectnessResult:
    """Read only the candidate and named hidden tests; the reference stays operator-held."""
    if arm_id not in ARM_IDS:
        return unavailable_result("unknown_arm")
    expected = fixture.per_arm_tree_digests.get(arm_id)
    if expected is None:
        return unavailable_result("missing_arm_baseline")
    if submission.baseline_tree_digest != expected:
        return unavailable_result("baseline_digest_mismatch")
    if runner.settings.image != fixture.observed_runtime_image_digest:
        return unavailable_result("image_digest_mismatch")
    if (
        hidden_regression_ref not in fixture.hidden_tests
        or new_behavior_ref not in fixture.hidden_tests
    ):
        return unavailable_result("unfrozen_hidden_tests")
    if hidden_regression_ref == new_behavior_ref:
        return unavailable_result("duplicate_hidden_tests")
    if visible_regression.name != "visible_regression":
        return unavailable_result("invalid_visible_tests")
    try:
        hidden_regression = WorkflowTestGroup.model_validate_json(
            store.read_bytes(hidden_regression_ref)
        )
        new_behavior = WorkflowTestGroup.model_validate_json(store.read_bytes(new_behavior_ref))
        patch = store.read_bytes(submission.patch_ref).decode("utf-8")
    except (OSError, UnicodeError, ValueError, ObjectIntegrityError):
        return unavailable_result("fixture_asset_unavailable")
    if hidden_regression.name != "hidden_regression" or new_behavior.name != "new_behavior":
        return unavailable_result("invalid_hidden_tests")
    return await runner.run(
        baseline=baseline,
        baseline_tree_digest=expected,
        expected_tree_digest=submission.tree_digest,
        patch=patch,
        groups=(visible_regression, hidden_regression, new_behavior),
    )


def unavailable_result(cause: str) -> WorkflowCorrectnessResult:
    """A typed result for missing, invalid, or inaccessible evaluation inputs."""
    return WorkflowCorrectnessResult(
        "unavailable",
        tuple(
            GroupResult(name, "unavailable", cause)
            for name in ("visible_regression", "hidden_regression", "new_behavior")
        ),
        cause,
    )
