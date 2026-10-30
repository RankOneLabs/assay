"""Bind workflow correctness inputs to the frozen fixture and object store.

``evaluate_candidate`` grades against a single-arm ``assay-fixture-manifest/0.1.0``
(the wf-13 smoke). ``evaluate_task_candidate`` and ``CellEvaluator`` grade one
study cell against ``assay-fixture-manifest/0.2.0`` per spec section 8.1: the
arm comes from the cell coordinate, the baseline from the realization the
worker was given, the baseline digest from the worker's own evidence, the task
record by subject and the test groups by name.
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from assay.execution import EvaluationFailed, EvaluationResult, EvaluationSuccess
from assay.fixture_manifest import FixtureManifest, FixtureManifestV2, fixture_identity
from assay.investigations.workflow_correctness import (
    DockerWorkflowRunner,
    GroupName,
    GroupResult,
    PreflightResult,
    WorkflowCorrectnessResult,
    WorkflowTestGroup,
    attribute_cause,
    workflow_tree_digest,
)
from assay.models import EvaluationCoordinate
from assay.pier_protocol import CandidateSubmission
from assay.store import ObjectIntegrityError, ObjectStore
from workflow_edit.arms import ARM_IDS

CORRECTNESS_CATEGORIES = ("correct", "incorrect", "unavailable")
# Group name -> whether it is hidden; every study task must declare all three by name.
STUDY_GROUPS: tuple[tuple[GroupName, bool], ...] = (
    ("visible_regression", False),
    ("hidden_regression", True),
    ("new_behavior", True),
)


def envelope_bytes(store: ObjectStore, ref: str) -> bytes:
    """Undo ``PierAdapter``'s base64 envelope around a published artifact."""
    envelope = json.loads(store.read_bytes(ref))
    return base64.b64decode(envelope["content_base64"])


@dataclass(frozen=True, slots=True)
class WorkerCandidate:
    """A settled cell's patch and digests, every one read from the worker's evidence."""

    patch: bytes
    tree_digest: str
    baseline_tree_digest: str


def worker_candidate(store: ObjectStore, output: Mapping[str, Any]) -> WorkerCandidate:
    """Read the candidate from the cell output; raises on any missing or unreadable part.

    The baseline digest is the one the bridge recorded in ``result.json`` from
    the tree it actually materialized, never one recomputed from the fixture,
    so a worker given the wrong baseline cannot pass the baseline check.
    """
    result = json.loads(envelope_bytes(store, output["result_ref"]))
    baseline = result["baseline_tree_digest"]
    if not isinstance(baseline, str):
        raise ValueError("worker result has no baseline tree digest")
    return WorkerCandidate(
        patch=envelope_bytes(store, output["patch_ref"]),
        tree_digest=envelope_bytes(store, output["tree_digest_ref"]).decode("ascii"),
        baseline_tree_digest=baseline,
    )


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


async def evaluate_task_candidate(
    *,
    store: ObjectStore,
    manifest: FixtureManifestV2,
    subject_id: str,
    arm_id: str,
    baseline: Mapping[str, str],
    submission: CandidateSubmission,
    runner: DockerWorkflowRunner,
) -> WorkflowCorrectnessResult:
    """Grade one study cell; the reference and negative patches are never read.

    ``baseline`` is the repository of the realization the worker was given; it
    must be the manifest's tree for this subject and arm, and the worker's own
    recorded baseline digest must name that same tree.
    """
    task = manifest.task(subject_id)
    if task is None:
        return unavailable_result("unknown_subject")
    arm = next((record for key, record in task.arms.items() if key == arm_id), None)
    if arm is None:
        return unavailable_result("unknown_arm")
    if workflow_tree_digest(baseline) != arm.tree_digest:
        return unavailable_result("realization_digest_mismatch")
    if submission.baseline_tree_digest != arm.tree_digest:
        return unavailable_result("baseline_digest_mismatch")
    if runner.settings.image != manifest.observed_runtime_image_digest:
        return unavailable_result("image_digest_mismatch")
    refs = [task.group(name, hidden=hidden) for name, hidden in STUDY_GROUPS]
    if any(ref is None for ref in refs):
        return unavailable_result("missing_test_group")
    try:
        groups = tuple(
            WorkflowTestGroup.model_validate_json(store.read_bytes(ref.digest))
            for ref in refs
            if ref is not None
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


def cell_arm(coordinate: EvaluationCoordinate) -> tuple[str, str]:
    """The subject and arm of the evaluated cell; identifiers cannot contain ``:``."""
    subject_id, arm_id, _repeat = coordinate.cell_id.split(":")
    return subject_id, arm_id


@dataclass
class CellEvaluator:
    """The per-cell study evaluator: every input comes from the cell, never a fixed arm."""

    store: ObjectStore
    manifest: FixtureManifestV2
    runner: DockerWorkflowRunner
    records: dict[str, dict[str, Any]] = field(default_factory=dict)

    def configuration(self) -> dict[str, Any]:
        return {
            "id": "workflow-edit-correctness",
            "version": "2",
            "categories": list(CORRECTNESS_CATEGORIES),
            "runner": self.runner.configuration(),
            "fixture": fixture_identity(self.manifest),
        }

    async def evaluate(
        self, *, input_value: Any, output: Any, coordinate: EvaluationCoordinate
    ) -> EvaluationResult:
        started = time.monotonic()
        subject_id, arm_id = cell_arm(coordinate)
        try:
            if output["cell_id"] != coordinate.cell_id:
                return EvaluationFailed("MismatchedCell", "output belongs to another cell")
            candidate = worker_candidate(self.store, output)
            baseline = input_value["repository"]
        except (KeyError, TypeError, ValueError, ObjectIntegrityError, OSError) as error:
            return EvaluationFailed("MissingCandidate", f"unreadable candidate: {error}")
        submission = CandidateSubmission(
            patch_ref=str(self.store.publish_bytes(candidate.patch)),
            tree_digest=candidate.tree_digest,
            baseline_tree_digest=candidate.baseline_tree_digest,
        )
        result = await evaluate_task_candidate(
            store=self.store,
            manifest=self.manifest,
            subject_id=subject_id,
            arm_id=arm_id,
            baseline=baseline,
            submission=submission,
            runner=self.runner,
        )
        return record_result(
            self.records, coordinate, result, empty_patch=candidate.patch == b"", started=started
        )


def record_result(
    records: dict[str, dict[str, Any]],
    coordinate: EvaluationCoordinate,
    result: WorkflowCorrectnessResult,
    *,
    empty_patch: bool,
    started: float,
) -> EvaluationSuccess:
    """Keep the cell's verdict for evidence and return it as the evaluation result."""
    groups = {item.name: {"status": item.status, "cause": item.cause} for item in result.groups}
    records[coordinate.cell_id] = {
        "verdict": result.verdict,
        "cause": result.cause,
        "groups": groups,
        "empty_patch": empty_patch,
        "seconds": round(time.monotonic() - started, 3),
    }
    return EvaluationSuccess(
        result.verdict,
        (result.cause,) if result.cause else (),
        {"groups": groups, "empty_patch": empty_patch},
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
        PreflightResult("unavailable", cause),
        attribute_cause(cause),
    )
