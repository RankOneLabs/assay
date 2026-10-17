"""The study plan is constructed from the derived fixture population."""

import json
from pathlib import Path

from assay.models import ExecutionPlanV3, RuntimeProfile, StudySnapshot
from assay.store import ObjectStore
from verification_pilot.arms import ALL_ARMS, TIER_1_ARMS
from verification_pilot.fixtures import base_subjects, pilot_sessions
from verification_pilot.study import FINAL_CEILING, compile_pilot_plan, pilot_subjects


def test_study_plan_uses_fixture_subjects_and_sessions(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    runtime = RuntimeProfile(id="scripted", version="1",
                             configuration_ref=str(store.publish_json({"scripted": True})))
    prepared = compile_pilot_plan(store, runtime,
                                  worker_configuration={"id": "scripted", "version": "1"})
    plan = ExecutionPlanV3.model_validate_json(prepared.plan_bytes)
    fixture_subjects = base_subjects()
    sessions = pilot_sessions(fixture_subjects)
    assert len(fixture_subjects) == len(prepared.subjects) == 16
    assert tuple(subject.id for subject in prepared.subjects) == tuple(
        subject.id for subject in fixture_subjects)
    assert len(sessions) == len(plan.cells) == 24
    assert {(cell.subject_id, cell.arm_id) for cell in plan.cells} == {
        (session.subject_id, session.arm_id) for session in sessions}
    assert len(prepared.snapshot.realizations) == 16 * len(ALL_ARMS)
    assert len(plan.exclusions) == 16 * len(ALL_ARMS) - 24
    assert plan.worker_repeats == 1
    assert plan.ceiling == FINAL_CEILING
    assert {cell.arm_id for cell in plan.cells} == set(TIER_1_ARMS)
    assert len(prepared.snapshot.evaluators) == 1
    assert StudySnapshot.model_validate(prepared.snapshot.model_dump(mode="json")) == (
        prepared.snapshot)
    payloads = [json.loads(store.read_bytes(subject.payload_ref))
                for subject in prepared.snapshot.subjects]
    assert {payload["migration"] for payload in payloads} == {
        subject.migration.name for subject in pilot_subjects()}
