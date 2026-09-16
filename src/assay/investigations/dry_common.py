"""Backend-neutral pieces of the DRY consistency experiment.

Golden materialization -- the fixed 12-task population, its repositories, and
the shape asserted by ``validate_experiment_shape`` -- lives here so it can be
imported, and tested, without the Jig-coupled worker/runner stack that
``assay.investigations.dry_experiment`` layers on top of it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from assay.canonical import canonical_json, digest_bytes
from assay.investigations.consistency import EXPERIMENT_TASKS, CodingTask
from assay.models import ExecutionPlan, StudySnapshot
from assay.store import ObjectStore


def publish_plan_dependencies(store: ObjectStore, snapshot: StudySnapshot) -> None:
    """Publish every snapshot-derived object referenced directly by compile_plan."""
    for declaration in (*snapshot.arms, *snapshot.evaluators):
        store.publish_json(declaration.model_dump(mode="json"))
    store.publish_json([arm.conditions for arm in sorted(snapshot.arms, key=lambda item: item.id)])


def repository_for(
    task: CodingTask,
    arm_id: str,
    repository_variants: Mapping[str, Mapping[str, Mapping[str, str]]] | None,
) -> dict[str, str]:
    if repository_variants is not None:
        try:
            return dict(repository_variants[task.id][arm_id])
        except KeyError as error:
            raise ValueError(f"missing {arm_id} repository for task {task.id}") from error
    example = task.reused_source if arm_id == "clean" else task.duplicated_source
    return {
        task.target_path: (
            task.helper_source + "\n" + example.replace("implement", "existing_feature")
        )
    }


def validate_experiment_shape(
    store: ObjectStore,
    snapshot: StudySnapshot,
    plan: ExecutionPlan,
    *,
    tasks: Sequence[CodingTask] = EXPERIMENT_TASKS,
    repository_variants: Mapping[str, Mapping[str, Mapping[str, str]]] | None = None,
    expected_subjects: int = 12,
    expected_cells: int = 48,
    expected_evaluations: int = 96,
) -> None:
    """Reject any drift from the fixed, golden 12-task DRY population/grid."""
    tasks_by_id = {task.id: task for task in tasks}
    if len(tasks_by_id) != expected_subjects or {
        subject.id for subject in snapshot.subjects
    } != set(tasks_by_id):
        raise ValueError("consistency experiment subject population changed")
    if {arm.id for arm in snapshot.arms} != {"clean", "inconsistent"}:
        raise ValueError("consistency experiment arms changed")
    if {arm.conditions.get("assay_execution_schedule") for arm in snapshot.arms} != {
        "subject-counterbalanced-v1"
    }:
        raise ValueError("consistency experiment execution schedule changed")
    if any(item.repeats != 1 for item in snapshot.evaluators):
        raise ValueError("consistency experiment evaluator repeats changed")
    if (
        plan.concurrency != 1
        or plan.worker_repeats != 2
        or len(plan.cells) != expected_cells
        or len(plan.evaluations) != expected_evaluations
    ):
        raise ValueError("consistency experiment execution grid changed")

    subjects = {subject.id: subject for subject in snapshot.subjects}
    realizations = {
        (realization.subject_id, realization.arm_id): realization
        for realization in snapshot.realizations
    }
    for task in tasks:
        task_value = task.model_dump(mode="json", exclude={"reused_source", "duplicated_source"})
        subject_ref = digest_bytes(canonical_json(task_value))
        subject = subjects[task.id]
        if (
            subject.label != task.instruction
            or subject.partition != task.family
            or subject.digest != subject_ref
            or subject.payload_ref != subject_ref
        ):
            raise ValueError("consistency experiment subject declaration changed")
        for arm_id in ("clean", "inconsistent"):
            repository = repository_for(task, arm_id, repository_variants)
            expected = {
                "task": task_value,
                "repository": repository,
                "base_subject_ref": subject_ref,
            }
            realization = realizations[(task.id, arm_id)]
            expected_ref = digest_bytes(canonical_json(expected))
            if realization.digest != expected_ref or realization.artifact_ref != expected_ref:
                raise ValueError("consistency experiment realization declaration changed")
            stored_value = json.loads(store.read_bytes(expected_ref))
            if canonical_json(stored_value) != canonical_json(expected):
                raise ValueError("consistency experiment realization content changed")
