"""Part 2a multi-arm study wiring.

``prepare_study`` builds four realizations per subject (``mess-00``,
``mess-low``, ``mess-mid``, ``mess-high``, each its own repository tree), puts
``subject-rotated-v1`` in every arm's conditions, and refuses the plan with
``shape.validate_worker_grid`` before any authorization exists. Its evaluator is
the per-cell ``CellEvaluator``. The single-arm wf-13 smoke stays on
``qualify.prepare``; its subject is refused by the study grid by design.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from assay.canonical import digest_bytes
from assay.fixture_manifest import FixtureManifestV2, fixture_identity, task_record_digest
from assay.investigations.workflow_correctness import DockerWorkflowRunner, workflow_tree_digest
from assay.models import (
    Arm,
    ExecutionCeiling,
    ExecutionPlanV3,
    Realization,
    RuntimeProfile,
    Subject,
)
from assay.store import ObjectStore
from workflow_edit.arms import ARM_IDS
from workflow_edit.evaluation import CellEvaluator
from workflow_edit.fixture import VISIBLE_PREFIX
from workflow_edit.qualify import (
    PlanKind,
    Prepared,
    Qualification,
    WorkflowEditWorker,
    bridge_worker,
    compile_workflow_plan,
)
from workflow_edit.shape import validate_worker_grid

STUDY_SCHEDULE = "subject-rotated-v1"
STUDY_PLAN = PlanKind(
    task="workflow_edit_2a",
    description="Part 2a controlled-messiness dose study",
    payload_schema="https://assay.local/schemas/workflow-edit-2a-correctness-v1.json",
    partition="study",
)


@dataclass(frozen=True)
class StudySubject:
    """One subject's four repository trees, keyed by arm id."""

    subject_id: str
    realizations: Mapping[str, Mapping[str, str]]


@dataclass(frozen=True)
class StudyFixture:
    """A 0.2.0 manifest and the operator-side trees its arm digests name."""

    manifest: FixtureManifestV2
    subjects: tuple[StudySubject, ...]


def check_fixture(fixture: StudyFixture, *, image: str, routing_digest: str | None) -> None:
    """Refuse a fixture whose trees, image, routing or qualification do not match its manifest."""
    manifest = fixture.manifest
    if manifest.observed_runtime_image_digest != image:
        raise ValueError("the fixture was qualified on another image")
    if manifest.routing_config_digest != routing_digest:
        raise ValueError("the fixture was qualified under another routing configuration")
    subject_ids = [subject.subject_id for subject in fixture.subjects]
    if sorted(subject_ids) != [task.subject_id for task in manifest.tasks]:
        raise ValueError("study subjects must be exactly the manifest's task records")
    for subject in fixture.subjects:
        task = manifest.task(subject.subject_id)
        assert task is not None
        if set(subject.realizations) != set(ARM_IDS):
            raise ValueError(f"{subject.subject_id} must have one realization per arm")
        for arm_id, record in task.arms.items():
            tree = subject.realizations[arm_id]
            if workflow_tree_digest(tree) != record.tree_digest:
                raise ValueError(f"{subject.subject_id} {arm_id} tree differs from its manifest")
            if not record.qualification.qualified:
                raise ValueError(f"{subject.subject_id} {arm_id} has not qualified")
        # Exposed tests are fixed across arms (spec 5.1); only treated sites differ.
        visible = [
            {path: text for path, text in tree.items() if path.startswith(VISIBLE_PREFIX)}
            for tree in subject.realizations.values()
        ]
        if any(files != visible[0] for files in visible):
            raise ValueError(f"{subject.subject_id} visible tests differ between arms")


def plan_study(
    store: ObjectStore,
    fixture: StudyFixture,
    *,
    worker: WorkflowEditWorker,
    runner: DockerWorkflowRunner,
    runtime: RuntimeProfile,
    image: str,
    routing_digest: str | None,
    repeats: int,
    ceiling: ExecutionCeiling,
) -> Prepared:
    """Authorize a full subject x arm x repeat grid, validated before authorization."""
    check_fixture(fixture, image=image, routing_digest=routing_digest)
    if runner.settings.image != image:
        raise ValueError("the evaluator runs another image")
    manifest = fixture.manifest
    identity = fixture_identity(manifest)
    evaluator = CellEvaluator(store, manifest, runner)
    subjects: list[Subject] = []
    realizations: list[Realization] = []
    for subject in sorted(fixture.subjects, key=lambda item: item.subject_id):
        task = manifest.task(subject.subject_id)
        assert task is not None
        payload = str(store.publish_json({
            "task": task.task_prompt, "fixture": identity, "task_record": task_record_digest(task),
        }))
        subjects.append(Subject(id=subject.subject_id, label=subject.subject_id,
                                partition=STUDY_PLAN.partition, digest=payload,
                                payload_ref=payload))
        for arm_id in ARM_IDS:
            # The instruction is the task record's, byte-identical on every arm.
            ref = str(store.publish_json({
                "task": task.task_prompt, "repository": dict(subject.realizations[arm_id]),
            }))
            realizations.append(Realization(subject_id=subject.subject_id, arm_id=arm_id,
                                            digest=ref, artifact_ref=ref))
    arms = tuple(
        Arm(id=arm_id, worker=worker.configuration(arm_id), intervention={"dose": arm_id},
            conditions={"assay_execution_schedule": STUDY_SCHEDULE})
        for arm_id in ARM_IDS
    )

    def check(plan: ExecutionPlanV3) -> None:
        validate_worker_grid(
            subject_ids=[subject.id for subject in subjects],
            arm_ids=[arm.id for arm in arms],
            cells=plan.cells,
            worker_repeats=repeats,
        )

    snapshot, plan_bytes = compile_workflow_plan(
        store,
        STUDY_PLAN,
        subjects=tuple(subjects),
        arms=arms,
        realizations=tuple(realizations),
        evaluator_configuration=evaluator.configuration(),
        runtime=runtime,
        repeats=repeats,
        ceiling=ceiling,
        check=check,
    )
    return Prepared(
        snapshot=snapshot,
        plan_bytes=plan_bytes,
        authorization=digest_bytes(plan_bytes),
        worker=worker,
        evaluator=evaluator,
        manifest=manifest,
    )


def prepare_study(
    q: Qualification, fixture: StudyFixture, *, repeats: int, ceiling: ExecutionCeiling
) -> Prepared:
    """The live study path: the bridge worker on every arm, the Docker evaluator per cell."""
    worker, runtime = bridge_worker(q)
    return plan_study(
        q.store,
        fixture,
        worker=worker,
        runner=q.runner(),
        runtime=runtime,
        image=q.image,
        routing_digest=q.factory().configuration()["routing_config_digest"],
        repeats=repeats,
        ceiling=ceiling,
    )
