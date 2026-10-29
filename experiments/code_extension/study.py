"""Authorize an extension study only from qualified, unchanged scenario fixtures."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from workflow_edit.qualify import PlanKind, compile_workflow_plan

from assay.canonical import canonical_json, digest_bytes
from assay.execution import CoordinateAwareWorker, RunResult, Worker, execute_plan
from assay.fixture_manifest import FixtureManifestV3
from assay.investigations.workflow_correctness import (
    DockerWorkflowRunner,
    WorkflowTestGroup,
    workflow_tree_digest,
)
from assay.models import (
    Arm,
    ExecutionCeiling,
    ExecutionPlanV3,
    Realization,
    RuntimeProfile,
    StudySnapshot,
    Subject,
)
from assay.store import ObjectIntegrityError, ObjectStore
from code_extension.evaluation import CellEvaluator
from code_extension.fixture import PILOT, VISIBLE_PREFIX, load_fixture
from code_extension.shape import validate_worker_grid

STUDY_GROUPS = (("visible_regression", False), ("hidden_regression", True), ("new_behavior", True))
STUDY_SCHEDULE = "subject-rotated-v1"
STUDY_PLAN = PlanKind(
    task="code_extension_spec3",
    description="Spec 3 code-extension correctness study",
    payload_schema="https://assay.local/schemas/code-extension-spec3-correctness-v1.json",
    partition="study",
)


@dataclass(frozen=True)
class StudyScenario:
    """Operator-held repository trees for one manifest scenario."""

    subject_id: str
    realizations: Mapping[str, Mapping[str, str]]


@dataclass(frozen=True)
class StudyFixture:
    manifest: FixtureManifestV3
    scenarios: tuple[StudyScenario, ...]


def check_fixture(
    fixture: StudyFixture, *, store: ObjectStore, image: str, routing_digest: str | None
) -> None:
    """Refuse drifted or unqualified inputs before a plan can be authorized."""
    manifest = fixture.manifest
    if manifest.observed_runtime_image_digest != image:
        raise ValueError("the fixture was qualified on another image")
    if manifest.routing_config_digest != routing_digest:
        raise ValueError("the fixture was qualified under another routing configuration")
    if sorted(item.subject_id for item in fixture.scenarios) != [
        item.subject_id for item in manifest.scenarios
    ]:
        raise ValueError("study scenarios must be exactly the manifest's scenarios")
    for item in fixture.scenarios:
        scenario = manifest.scenario(item.subject_id)
        assert scenario is not None
        if set(item.realizations) != set(manifest.arm_set.arm_ids):
            raise ValueError(f"{item.subject_id} must have one realization per declared arm")
        refs = [
            next(
                (group for group in (scenario.hidden_tests if hidden else scenario.visible_tests)
                 if group.name == name),
                None,
            )
            for name, hidden in STUDY_GROUPS
        ]
        if any(ref is None for ref in refs):
            raise ValueError(f"{item.subject_id} lacks study test groups")
        try:
            groups = tuple(
                WorkflowTestGroup.model_validate_json(store.read_bytes(ref.digest))
                for ref in refs if ref is not None
            )
        except (OSError, ValueError, ObjectIntegrityError) as error:
            raise ValueError(f"{item.subject_id} has unreadable test groups") from error
        if [group.name for group in groups] != [name for name, _ in STUDY_GROUPS] or [
            group.restores for group in groups
        ] != [not hidden for _, hidden in STUDY_GROUPS]:
            raise ValueError(f"{item.subject_id} has invalid study test groups")
        visible_group = groups[0]
        hidden_paths = set(groups[1].files) | set(groups[2].files)
        visible: list[dict[str, str]] = []
        for arm in scenario.arms:
            tree = item.realizations[arm.arm_id]
            if not arm.qualification.qualified:
                raise ValueError(f"{item.subject_id} {arm.arm_id} has not qualified")
            if workflow_tree_digest(tree) != arm.tree_digest:
                raise ValueError(f"{item.subject_id} {arm.arm_id} tree differs from its manifest")
            if hidden_paths & tree.keys() or any(path.startswith("tests/hidden/") for path in tree):
                raise ValueError(f"{item.subject_id} {arm.arm_id} contains hidden tests")
            tree_visible = {
                path: source for path, source in tree.items() if path.startswith(VISIBLE_PREFIX)
            }
            visible.append(tree_visible)
        if any(files != visible[0] for files in visible):
            raise ValueError(f"{item.subject_id} visible tests differ between arms")
        if visible[0] != visible_group.files:
            raise ValueError(f"{item.subject_id} visible group lacks coverage")
        for arm in scenario.arms:
            for check_name in ("baseline_passes", "feature_fails", "reference_passes"):
                claimed = getattr(arm.qualification, check_name)
                try:
                    evidence = json.loads(store.read_bytes(claimed.evidence))
                    if (
                        evidence["schema_version"] != "assay-extension-qualification-record/0.1.0"
                        or evidence["subject_id"] != item.subject_id
                        or evidence["arm_id"] != arm.arm_id
                        or evidence["check"] != check_name
                        or evidence["image_digest"] != image
                        or evidence["tree_digest"] != arm.tree_digest
                        or evidence["outcome"] != claimed.outcome
                    ):
                        raise ValueError("claimed outcome differs from evidence")
                except (OSError, ValueError, KeyError, TypeError, ObjectIntegrityError) as error:
                    raise ValueError(
                        f"{item.subject_id} {arm.arm_id} {check_name} evidence mismatch"
                    ) from error


def load_pilot_study_fixture(store: ObjectStore) -> StudyFixture:
    """Load the committed qualified pilot and publish its frozen assets locally."""
    manifest = FixtureManifestV3.model_validate_json(
        (PILOT / "qualification" / "manifest.json").read_bytes()
    )
    pilot = load_fixture()
    for group in pilot.groups:
        store.publish_bytes(canonical_json(group.model_dump(mode="json")))
    for arm in manifest.scenarios[0].arms:
        for check in ("baseline_passes", "feature_fails", "reference_passes"):
            record_path = PILOT / "qualification" / "evidence" / arm.arm_id / f"{check}.json"
            data = record_path.read_bytes()
            if digest_bytes(data) != getattr(arm.qualification, check).evidence:
                raise ValueError(f"pilot qualification evidence differs: {arm.arm_id}/{check}")
            store.publish_bytes(data)
    return StudyFixture(manifest, (StudyScenario(manifest.scenarios[0].subject_id, {
        arm.arm_id: pilot.repository for arm in manifest.scenarios[0].arms
    }),))


@dataclass(frozen=True)
class PreparedStudy:
    snapshot: StudySnapshot
    plan_bytes: bytes
    authorization: str
    workers: dict[str, Worker | CoordinateAwareWorker]
    evaluator: CellEvaluator
    manifest: FixtureManifestV3


def plan_study(
    store: ObjectStore,
    fixture: StudyFixture,
    *,
    workers: Mapping[str, CoordinateAwareWorker],
    runner: DockerWorkflowRunner,
    runtime: RuntimeProfile,
    image: str,
    routing_digest: str | None,
    repeats: int,
    ceiling: ExecutionCeiling,
) -> PreparedStudy:
    """Compile the full scenario x declared-arm grid after every fixture gate."""
    check_fixture(fixture, store=store, image=image, routing_digest=routing_digest)
    if runner.settings.image != image:
        raise ValueError("the evaluator runs another image")
    manifest = fixture.manifest
    if set(workers) != set(manifest.arm_set.arm_ids):
        raise ValueError("workers must cover exactly the declared arm set")
    identity = digest_bytes(canonical_json(manifest.model_dump(mode="json")))
    evaluator = CellEvaluator(store, manifest, runner)
    subjects: list[Subject] = []
    realizations: list[Realization] = []
    for item in sorted(fixture.scenarios, key=lambda scenario: scenario.subject_id):
        scenario = manifest.scenario(item.subject_id)
        assert scenario is not None
        payload = str(store.publish_json({
            "fixture": identity,
            "scenario": digest_bytes(canonical_json(scenario.model_dump(mode="json"))),
            "feature_request": scenario.feature_request,
            "visible_requirements": list(scenario.visible_requirements),
        }))
        subjects.append(Subject(
            id=item.subject_id, label=item.subject_id, partition=STUDY_PLAN.partition,
            digest=payload, payload_ref=payload,
        ))
        for arm in scenario.arms:
            ref = str(store.publish_json({
                "task": arm.task_prompt,
                "repository": dict(item.realizations[arm.arm_id]),
            }))
            realizations.append(Realization(
                subject_id=item.subject_id, arm_id=arm.arm_id, digest=ref, artifact_ref=ref,
            ))
    arms = tuple(
        Arm(
            id=arm_id, worker=workers[arm_id].configuration(arm_id),
            intervention={"factor": manifest.arm_set.factor, "arm": arm_id},
            conditions={"assay_execution_schedule": STUDY_SCHEDULE},
        )
        for arm_id in manifest.arm_set.arm_ids
    )

    def check(plan: ExecutionPlanV3) -> None:
        validate_worker_grid(
            subject_ids=[subject.id for subject in subjects],
            arm_ids=manifest.arm_set,
            cells=plan.cells,
            worker_repeats=repeats,
        )

    snapshot, plan_bytes = compile_workflow_plan(
        store, STUDY_PLAN, subjects=tuple(subjects), arms=arms,
        realizations=tuple(realizations), evaluator_configuration=evaluator.configuration(),
        runtime=runtime, repeats=repeats, ceiling=ceiling, check=check,
    )
    return PreparedStudy(
        snapshot, plan_bytes, digest_bytes(plan_bytes),
        dict[str, Worker | CoordinateAwareWorker](workers), evaluator, manifest,
    )


def prepare_study(
    store: ObjectStore,
    fixture: StudyFixture,
    *,
    workers: Mapping[str, CoordinateAwareWorker],
    runner: DockerWorkflowRunner,
    runtime: RuntimeProfile,
    routing_config: Path | None,
    repeats: int,
    ceiling: ExecutionCeiling,
) -> PreparedStudy:
    """Bind the runner and current routing file to the qualified manifest."""
    routing_digest = digest_bytes(routing_config.read_bytes()) if routing_config else None
    return plan_study(
        store, fixture, workers=workers, runner=runner, runtime=runtime,
        image=runner.settings.image, routing_digest=routing_digest,
        repeats=repeats, ceiling=ceiling,
    )


async def run_study(prepared: PreparedStudy, store: ObjectStore) -> RunResult:
    """Use the core run manifest for complete and incomplete coordinates."""
    return await execute_plan(
        plan_bytes=prepared.plan_bytes,
        authorization=prepared.authorization,
        snapshot=prepared.snapshot,
        store=store,
        workers=prepared.workers,
        evaluators={"correctness": prepared.evaluator},
    )
