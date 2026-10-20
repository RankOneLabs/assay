"""Compile the pilot snapshot and its authorized 0.3.0 tier shards.

The compiler follows ``workflow_edit.qualify.compile_workflow_plan``: publish
declarations and schemas, compile with ``compile_plan_v2``, add the 0.3.0
ceiling, validate the grid, then return canonical bytes for authorization.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import paa_contracts

from assay.canonical import canonical_json, digest_bytes
from assay.models import (
    Arm,
    EvaluatorDeclaration,
    Exclusion,
    ExecutionCeiling,
    ExecutionPlanV3,
    Realization,
    RuntimeProfile,
    StudySnapshot,
    Subject,
)
from assay.planning import compile_plan_v2
from assay.store import ObjectStore
from verification_pilot.arms import ALL_ARMS, SCHEDULE, TIER_1_ARMS, placement_for
from verification_pilot.evaluation import EVALUATOR_IDS, REPORT_CATEGORIES
from verification_pilot.fixture import PilotFixture, load_fixture, subject_repository
from verification_pilot.fixtures import base_subjects, pilot_sessions
from verification_pilot.migrations import MIGRATIONS, Migration, OwnershipGroup
from verification_pilot.prompts import task_prompt
from verification_pilot.session import contributor_blocks, rotated_blocks
from verification_pilot.shape import validate_worker_grid

VERIFIER_OWN_GROUP: OwnershipGroup = "group_a"
FINAL_CEILING = ExecutionCeiling(max_cells=96, max_wall_time_seconds=345_600,
                                  max_fleet_occupancy=1)
PAYLOAD_SCHEMA = "https://assay.local/schemas/verification-pilot-measure-v1.json"


@dataclass(frozen=True, slots=True)
class PilotSubject:
    id: str
    migration: Migration
    location: str | None
    group: OwnershipGroup | None
    rotation: int
    repository: dict[str, str]


@dataclass(frozen=True, slots=True)
class PreparedPilot:
    snapshot: StudySnapshot
    plan_bytes: bytes
    authorization: str
    subjects: tuple[PilotSubject, ...]


def pilot_subjects(fixture: PilotFixture | None = None) -> tuple[PilotSubject, ...]:
    """Materialize the 16 base subjects defined by the raw slice."""
    fixture = fixture or load_fixture()
    result = [PilotSubject(
        id=subject.id, migration=subject.migration, location=subject.location,
        group=subject.owner, rotation=0,
        repository=subject_repository(subject, fixture),
    ) for subject in base_subjects(MIGRATIONS)]
    if len(result) != 16:
        raise ValueError("pilot must have 16 base subjects")
    return tuple(result)


def smoke_subject_ids(subjects: tuple[PilotSubject, ...]) -> tuple[str, ...]:
    """The registered live smoke: every rename's verifier-owned planted subject."""
    selected = tuple(s.id for s in subjects if s.group == VERIFIER_OWN_GROUP)
    if len(selected) != len(MIGRATIONS):
        raise ValueError("live smoke requires one verifier-owned subject per rename")
    return selected


def _exclusions(
    subjects: tuple[Subject, ...], active_arms: tuple[str, ...],
    active_subject_ids: tuple[str, ...], session_pairs: frozenset[tuple[str, str]],
) -> tuple[Exclusion, ...]:
    exclusions: list[Exclusion] = []
    for subject in subjects:
        for arm_id in ALL_ARMS:
            if (arm_id in active_arms and subject.id in active_subject_ids
                    and (subject.id, arm_id) in session_pairs):
                continue
            classification = ("clean_control" if subject.id.endswith("-clean")
                              else "deferred_tier" if arm_id not in active_arms
                              else "qualification_smoke")
            exclusions.append(Exclusion(
                subject_id=subject.id, arm_id=arm_id, classification=classification,
                reason="Coordinate excluded from this fixture-derived shard",
            ))
    return tuple(exclusions)


def compile_pilot_plan(store: ObjectStore, runtime: RuntimeProfile, *,
                       worker_configuration: dict[str, Any],
                       worker_configurations: Mapping[str, dict[str, Any]] | None = None,
                       active_arms: tuple[str, ...] = TIER_1_ARMS,
                       active_subject_ids: tuple[str, ...] | None = None,
                       subjects_data: tuple[PilotSubject, ...] | None = None,
                       ceiling: ExecutionCeiling = FINAL_CEILING) -> PreparedPilot:
    """Build one full snapshot and one shard; check before returning authorization."""
    subjects_data = subjects_data or pilot_subjects()
    if len(subjects_data) != 16 or len({s.id for s in subjects_data}) != 16:
        raise ValueError("pilot requires exactly 16 unique base subjects")
    sessions = pilot_sessions(base_subjects(MIGRATIONS))
    fixture_pairs = frozenset((session.subject_id, session.arm_id) for session in sessions)
    if len(fixture_pairs) != 24:
        raise ValueError("pilot requires 24 unique fixture-derived sessions")
    session_pairs = frozenset(
        (session.subject_id, arm_id) for session in sessions for arm_id in active_arms
        if arm_id.endswith(session.arm_id.split("-", 1)[1])
    )
    session_subject_ids = tuple(dict.fromkeys(session.subject_id for session in sessions))
    active_subject_ids = (session_subject_ids if active_subject_ids is None
                          else active_subject_ids)

    def publish(value: Any) -> str:
        return str(store.publish_json(value))

    subjects: list[Subject] = []
    realizations: list[Realization] = []
    for item in subjects_data:
        subject_ref = publish({"task": task_prompt(item.migration),
                               "migration": item.migration.name, "location": item.location,
                               "ownership_group": item.group, "own_group": VERIFIER_OWN_GROUP,
                               "rotation": item.rotation})
        subjects.append(Subject(id=item.id, label=item.id, partition="verification-pilot",
                                digest=subject_ref, payload_ref=subject_ref))
        ordered = rotated_blocks(contributor_blocks(item.migration), item.rotation)
        for arm_id in ALL_ARMS:
            realization_ref = publish({
                "task": task_prompt(item.migration), "repository": item.repository,
                "migration": item.migration.name, "location": item.location,
                "rotation": item.rotation, "blocks": [block.text for block in ordered],
                "placement": placement_for(arm_id), "tier": arm_id[:2],
            })
            realizations.append(Realization(subject_id=item.id, arm_id=arm_id,
                                            digest=realization_ref, artifact_ref=realization_ref))
    arms = tuple(Arm(id=arm_id, worker=(worker_configurations[arm_id]
                                         if worker_configurations is not None
                                         else worker_configuration),
                     intervention={"tier": arm_id[:2], "placement": placement_for(arm_id)},
                     conditions={"assay_execution_schedule": SCHEDULE}) for arm_id in ALL_ARMS)
    identity_basis = publish({"definition":
                              "Sealed first-turn trajectory and derived ownership map"})
    evaluators = []
    for evaluator_id in EVALUATOR_IDS:
        schema_id = PAYLOAD_SCHEMA.removesuffix(".json") + f"-{evaluator_id}.json"
        schema = {"$schema": "http://json-schema.org/draft-07/schema#",
                  "$id": schema_id, "allOf": [
                      {"$ref": "https://paa.dev/paa-evidence-record.schema.json"},
                      {"properties": {"verdict": {"properties": {
                          "value": {"enum": list(REPORT_CATEGORIES[evaluator_id])}}}}},
                  ]}
        evaluators.append(EvaluatorDeclaration(
            id=evaluator_id,
            identity={"property": evaluator_id, "target": "process",
                      "technique": "deterministic",
                      "evaluation_basis": {"kind": "invariant", "ref": identity_basis},
                      "epistemic_status": "proxy", "version": "1", "authority": "advisory"},
            payload_schema=schema_id, payload_schema_ref=publish(schema),
            basis_ref=identity_basis,
            configuration={"id_set": list(EVALUATOR_IDS), "version": "fixture-derived-v2"},
            repeats=1,
        ))
    task_declaration = {
        "task": "verification_pilot", "version": 1,
        "description": "Verify a symbol migration after contributor handoff",
        "boundary": {"input": "task_repository", "output": "verification_trajectory"},
        "initial_position": "manual", "deployment": "shadow",
        "evaluators": [e.identity for e in evaluators],
        "position_policy": {"manual": "offline", "hitl": "blocking"},
        "promotion": {"from": "manual", "to": "hitl", "report": "verification_pilot_report",
                      "window": {"kind": "cases", "size": 10}, "execution": "operator_approval"},
        "demotion": {"from": "hitl", "to": "manual", "trigger": "operator_decision",
                     "window": {"kind": "cases", "size": 1}},
    }
    snapshot = StudySnapshot(
        subjects=tuple(subjects), arms=arms, realizations=tuple(realizations),
        evaluators=tuple(evaluators), paa_task_ref=publish(task_declaration),
        pricing_catalog_ref=publish({"status": "route pricing pending operator qualification"}),
        task_schema_ref=publish(paa_contracts.load_schema("paa-task")),
        evidence_schema_ref=publish(paa_contracts.load_schema("paa-evidence-record")),
        operating_schema_ref=publish(paa_contracts.load_schema("paa-operating-record")),
    )
    snapshot_ref = publish(snapshot.model_dump(mode="json"))
    for declaration in (*snapshot.arms, *snapshot.evaluators):
        publish(declaration.model_dump(mode="json"))
    publish([arm.conditions for arm in snapshot.arms])
    base = compile_plan_v2(snapshot, snapshot_ref=snapshot_ref, worker_repeats=1,
                           exclusions=_exclusions(snapshot.subjects, active_arms,
                                                  active_subject_ids, session_pairs),
                           runtime=runtime, concurrency=1)
    plan = ExecutionPlanV3.model_validate({**base.model_dump(mode="json"),
                                            "schema_version": "assay-execution-plan/0.3.0",
                                            "ceiling": ceiling.model_dump(mode="json")})
    validate_worker_grid(subject_ids=[s.id for s in snapshot.subjects],
                         arm_ids=[a.id for a in snapshot.arms], cells=plan.cells,
                         worker_repeats=plan.worker_repeats, active_arms=active_arms,
                         active_subject_ids=active_subject_ids)
    if len(plan.cells) > ceiling.max_cells:
        raise ValueError("plan exceeds the final cell ceiling")
    plan_bytes = canonical_json(plan.model_dump(mode="json"))
    store.publish_bytes(plan_bytes)
    return PreparedPilot(snapshot, plan_bytes, digest_bytes(plan_bytes), subjects_data)
