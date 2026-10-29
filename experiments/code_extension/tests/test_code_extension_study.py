"""The extension fixture gate refuses drift before authorization exists."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from code_extension.fixture import VISIBLE_PREFIX
from code_extension.shape import validate_worker_grid
from code_extension.study import (
    StudyFixture,
    StudyScenario,
    check_fixture,
    load_pilot_study_fixture,
    plan_study,
    prepare_study,
)

from assay.canonical import canonical_json
from assay.execution import WorkerFailure
from assay.fixture_manifest import CodeShapeArmSet, FixtureManifestV3
from assay.investigations.workflow_correctness import (
    DockerWorkflowRunner,
    WorkflowRunnerSettings,
    workflow_tree_digest,
)
from assay.models import CellCoordinate, ExecutionCeiling, RuntimeProfile, parse_execution_plan
from assay.store import ObjectStore


def _pilot(tmp_path: Path) -> tuple[ObjectStore, StudyFixture]:
    store = ObjectStore(tmp_path / "store")
    fixture = load_pilot_study_fixture(store)
    check_fixture(
        fixture, store=store, image=fixture.manifest.observed_runtime_image_digest,
        routing_digest=fixture.manifest.routing_config_digest,
    )
    return store, fixture


def _check(store: ObjectStore, fixture: StudyFixture) -> None:
    check_fixture(
        fixture, store=store, image=fixture.manifest.observed_runtime_image_digest,
        routing_digest=fixture.manifest.routing_config_digest,
    )


def test_refuses_image_drift(tmp_path: Path) -> None:
    store, fixture = _pilot(tmp_path)
    with pytest.raises(ValueError, match="another image"):
        check_fixture(
            fixture, store=store, image="sha256:" + "f" * 64,
            routing_digest=fixture.manifest.routing_config_digest,
        )


def test_refuses_routing_drift(tmp_path: Path) -> None:
    store, fixture = _pilot(tmp_path)
    with pytest.raises(ValueError, match="another routing"):
        check_fixture(
            fixture, store=store, image=fixture.manifest.observed_runtime_image_digest,
            routing_digest=None,
        )


def test_refuses_unqualified_arm(tmp_path: Path) -> None:
    store, fixture = _pilot(tmp_path)
    wire = fixture.manifest.model_dump(mode="json")
    wire["scenarios"][0]["arms"][0]["qualification"]["feature_fails"]["outcome"] = "passed"
    changed = StudyFixture(FixtureManifestV3.model_validate(wire), fixture.scenarios)
    with pytest.raises(ValueError, match="has not qualified"):
        _check(store, changed)


def test_refuses_tree_drift(tmp_path: Path) -> None:
    store, fixture = _pilot(tmp_path)
    item = fixture.scenarios[0]
    tree = {**item.realizations["baseline"], "src/drift.ts": "changed\n"}
    changed = StudyFixture(fixture.manifest, (StudyScenario(item.subject_id, {"baseline": tree}),))
    with pytest.raises(ValueError, match="tree differs"):
        _check(store, changed)


def test_refuses_hidden_check_path_even_with_matching_tree_digest(tmp_path: Path) -> None:
    store, fixture = _pilot(tmp_path)
    item = fixture.scenarios[0]
    tree = {**item.realizations["baseline"], "tests/hidden/sneaky.test.ts": "// hidden\n"}
    wire = fixture.manifest.model_dump(mode="json")
    wire["scenarios"][0]["arms"][0]["tree_digest"] = workflow_tree_digest(tree)
    changed = StudyFixture(
        FixtureManifestV3.model_validate(wire),
        (StudyScenario(item.subject_id, {"baseline": tree}),),
    )
    with pytest.raises(ValueError, match="contains hidden tests"):
        _check(store, changed)


def test_refuses_visible_tests_that_differ_between_arms(tmp_path: Path) -> None:
    store, fixture = _pilot(tmp_path)
    item = fixture.scenarios[0]
    first = dict(item.realizations["baseline"])
    second = {**first, "src/shape.ts": "export const shape = 1;\n"}
    visible_path = next(path for path in first if path.startswith(VISIBLE_PREFIX))
    second[visible_path] += "// changed\n"
    wire = fixture.manifest.model_dump(mode="json")
    wire["arm_set"] = {"factor": "code_shape", "arm_ids": ["shape-a", "shape-b"]}
    first_arm = wire["scenarios"][0]["arms"][0]
    wire["scenarios"][0]["arms"] = [
        {**first_arm, "arm_id": "shape-a", "tree_digest": workflow_tree_digest(first)},
        {**first_arm, "arm_id": "shape-b", "tree_digest": workflow_tree_digest(second)},
    ]
    changed = StudyFixture(
        FixtureManifestV3.model_validate(wire),
        (StudyScenario(item.subject_id, {"shape-a": first, "shape-b": second}),),
    )
    with pytest.raises(ValueError, match="visible tests differ"):
        _check(store, changed)


def test_refuses_qualification_evidence_for_another_arm(tmp_path: Path) -> None:
    store, fixture = _pilot(tmp_path)
    wire = fixture.manifest.model_dump(mode="json")
    result = wire["scenarios"][0]["arms"][0]["qualification"]["baseline_passes"]
    record = json.loads(store.read_bytes(result["evidence"]))
    record["arm_id"] = "another-arm"
    result["evidence"] = str(store.publish_bytes(canonical_json(record) + b"\n"))
    with pytest.raises(ValueError, match="baseline_passes evidence mismatch"):
        _check(store, StudyFixture(FixtureManifestV3.model_validate(wire), fixture.scenarios))


def test_grid_refuses_a_mixed_factor_before_planning() -> None:
    mixed = CodeShapeArmSet.model_construct(
        factor=("code_shape", "model_profile"), arm_ids=("shape-a", "model-a")
    )
    with pytest.raises(ValueError, match="exactly one declared arm-set factor"):
        validate_worker_grid(
            subject_ids=("scenario",), arm_ids=mixed, cells=(), worker_repeats=1
        )


def _two_arm_fixture(store: ObjectStore, fixture: StudyFixture) -> StudyFixture:
    item = fixture.scenarios[0]
    first = dict(item.realizations["baseline"])
    second = {**first, "src/shape.ts": "export const shape = 1;\n"}
    trees = {"shape-a": first, "shape-b": second}
    wire = fixture.manifest.model_dump(mode="json")
    wire["arm_set"] = {"factor": "code_shape", "arm_ids": list(trees)}
    original = wire["scenarios"][0]["arms"][0]
    arms = []
    for arm_id, tree in trees.items():
        arm = {**original, "arm_id": arm_id, "tree_digest": workflow_tree_digest(tree)}
        arm["qualification"] = json.loads(json.dumps(original["qualification"]))
        for check in ("baseline_passes", "feature_fails", "reference_passes"):
            record = json.loads(store.read_bytes(arm["qualification"][check]["evidence"]))
            record["arm_id"] = arm_id
            record["tree_digest"] = arm["tree_digest"]
            arm["qualification"][check]["evidence"] = str(
                store.publish_bytes(canonical_json(record) + b"\n")
            )
        arms.append(arm)
    wire["scenarios"][0]["arms"] = arms
    return StudyFixture(
        FixtureManifestV3.model_validate(wire), (StudyScenario(item.subject_id, trees),)
    )


class PlanWorker:
    supports_cell_coordinates = True

    def configuration(self, arm_id: str) -> dict[str, Any]:
        return {"id": "plan-worker", "version": "1", "arm_id": arm_id}

    async def run_cell(self, *, input_value: Any, coordinate: CellCoordinate) -> WorkerFailure:
        raise AssertionError("planning must never dispatch")


def test_plan_uses_declared_factor_full_grid_and_rotated_schedule(tmp_path: Path) -> None:
    store, pilot = _pilot(tmp_path)
    fixture = _two_arm_fixture(store, pilot)
    _check(store, fixture)
    image = fixture.manifest.observed_runtime_image_digest
    prepared = plan_study(
        store, fixture, workers={arm: PlanWorker() for arm in fixture.manifest.arm_set.arm_ids},
        runner=DockerWorkflowRunner(WorkflowRunnerSettings(image=image, toolchain="bun")),
        runtime=RuntimeProfile(
            id="pier", version="scripted", configuration_ref=str(store.publish_json({"v": 1})),
        ),
        image=image, routing_digest=fixture.manifest.routing_config_digest, repeats=2,
        ceiling=ExecutionCeiling(max_cells=4, max_wall_time_seconds=600, max_fleet_occupancy=1),
    )
    plan = parse_execution_plan(json.loads(prepared.plan_bytes))
    assert prepared.authorization == str(store.publish_bytes(prepared.plan_bytes))
    assert [cell.arm_id for cell in plan.cells] == [
        "shape-a", "shape-b", "shape-b", "shape-a"
    ]
    assert all(
        arm.conditions == {"assay_execution_schedule": "subject-rotated-v1"}
        and arm.intervention["factor"] == "code_shape"
        for arm in prepared.snapshot.arms
    )
    assert len(prepared.snapshot.realizations) == 2


def test_prepare_reads_current_routing_file_before_planning(tmp_path: Path) -> None:
    store, fixture = _pilot(tmp_path)
    route = tmp_path / "routing.yaml"
    route.write_text("changed: route\n")
    image = fixture.manifest.observed_runtime_image_digest
    with pytest.raises(ValueError, match="another routing"):
        prepare_study(
            store, fixture, workers={"baseline": PlanWorker()},
            runner=DockerWorkflowRunner(WorkflowRunnerSettings(image=image, toolchain="bun")),
            runtime=RuntimeProfile(
                id="pier", version="scripted",
                configuration_ref=str(store.publish_json({"v": 1})),
            ),
            routing_config=route, repeats=1,
            ceiling=ExecutionCeiling(
                max_cells=1, max_wall_time_seconds=600, max_fleet_occupancy=1,
            ),
        )
    assert not any(
        b'"schema_version":"assay-execution-plan/0.3.0"' in path.read_bytes()
        for path in store.objects.iterdir()
    )
