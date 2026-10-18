"""Compile the self-trust snapshot and one authorized shard.

Subjects cross each concept with the model's own share and the remnant's
location: three planted locations and one clean control for each of the three
own shares, so 36 subjects. Two arms place the model's own log natively or
quoted. The compiler mirrors ``verification_pilot.study.compile_pilot_plan``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

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
from verification_pilot.fixtures import GROUPS, OwnershipGroup, read_raw_repository
from verification_pilot.self_trust.concepts import CONCEPTS, Concept, subject_repository
from verification_pilot.self_trust.evaluation import EVALUATOR_ID, VERDICTS
from verification_pilot.self_trust.ladder import REFACTOR, REWRITE, REWRITE_1, REWRITE_2, RUNGS
from verification_pilot.self_trust.refactor_session import LogOrder
from verification_pilot.self_trust.refactor_session import task_text as refactor_task_text
from verification_pilot.self_trust.session import Placement, task_text

ARMS: tuple[str, ...] = ("st-native", "st-quoted", "st-quoted-first", "st-quoted-last")
ATTRIBUTION_ORDER_ARMS: tuple[str, ...] = ("st-quoted-first", "st-quoted-last")
_ORDERS: dict[str, LogOrder] = {"st-native": "own_first", "st-quoted": "own_first",
                                "st-quoted-first": "holder_first",
                                "st-quoted-last": "holder_last"}
SCHEDULE = "subject-rotated-v1"
CEILING = ExecutionCeiling(max_cells=144, max_wall_time_seconds=518_400, max_fleet_occupancy=1)
PAYLOAD_SCHEMA = "https://assay.local/schemas/self-trust-measure-v1.json"


def placement_for(arm_id: str) -> Placement:
    if arm_id not in ARMS:
        raise ValueError(f"unknown self-trust arm: {arm_id}")
    return "native" if arm_id == "st-native" else "quoted"


def order_for(arm_id: str) -> LogOrder:
    """Where the omission holder's log sits; only refactor subjects vary it."""
    if arm_id not in ARMS:
        raise ValueError(f"unknown self-trust arm: {arm_id}")
    return _ORDERS[arm_id]


Fixture = Literal["rename", "refactor", "rewrite", "rewrite1", "rewrite2"]


@dataclass(frozen=True, slots=True)
class SelfTrustSubject:
    id: str
    concept: Concept | None
    own: OwnershipGroup
    remnant_owner: OwnershipGroup | None
    task: str
    repository: dict[str, str]
    fixture: Fixture = "rename"

    @property
    def concept_name(self) -> str:
        return self.concept.name if self.concept is not None else self.fixture

    @property
    def condition(self) -> Literal["own", "teammate", "clean"]:
        if self.remnant_owner is None:
            return "clean"
        return "own" if self.remnant_owner == self.own else "teammate"


@dataclass(frozen=True, slots=True)
class PreparedSelfTrust:
    snapshot: StudySnapshot
    plan_bytes: bytes
    authorization: str
    subjects: tuple[SelfTrustSubject, ...]


def subject_id(concept: str, own: str, remnant_owner: str | None) -> str:
    return f"{concept}-own_{own.removeprefix('group_')}-remnant_" + (
        remnant_owner.removeprefix("group_") if remnant_owner else "none")


def self_trust_subjects() -> tuple[SelfTrustSubject, ...]:
    """The 36 rename subjects, then 12 for each refactor rung (S, then L)."""
    repository = read_raw_repository()
    renames = tuple(
        SelfTrustSubject(
            id=subject_id(concept.name, own, remnant), concept=concept, own=own,
            remnant_owner=remnant, task=task_text(repository, concept, own),
            repository=subject_repository(repository, concept, remnant),
        )
        for concept in CONCEPTS for own in GROUPS for remnant in (*GROUPS, None))
    ladder: list[SelfTrustSubject] = []
    for rung in (REFACTOR, REWRITE, REWRITE_1, REWRITE_2):
        trees = {remnant: rung.subject_tree(remnant) for remnant in (*rung.order, None)}
        ladder += [
            SelfTrustSubject(
                id=subject_id(rung.name, own, remnant), concept=None, own=own,
                remnant_owner=remnant, task=refactor_task_text(own, rung),
                repository=trees[remnant], fixture=cast(Fixture, rung.name),
            )
            for own in GROUPS for remnant in (*rung.order, None)]
    return renames + tuple(ladder)


def calibration_subject_ids(subjects: tuple[SelfTrustSubject, ...],
                            concept: str = "stage_run") -> tuple[str, ...]:
    """Calibration step 1: every teammate-share remnant of one concept."""
    return tuple(s.id for s in subjects
                 if s.concept_name == concept and s.condition == "teammate")


def refactor_calibration_ids(subjects: tuple[SelfTrustSubject, ...],
                             rung: str = "refactor") -> tuple[str, ...]:
    """The matched own/teammate pairs for a rung: one per share that can hold the omission.

    For each such share, one cell where it is the model's own and one where it
    is not, so the omission's file and line are fixed and only its author
    differs. With two or more shares the other owner is the next share in the
    rung; a one-share rung's other cell has the model verify a teammate's work.
    """
    by_id = {s.id: s for s in subjects}
    order = RUNGS[rung].order if rung in RUNGS else GROUPS

    # A three-share rung keeps the pairing S was first run with, in group order.
    holders = GROUPS if len(order) == 3 else order

    def teammate(holder: OwnershipGroup) -> OwnershipGroup:
        pool = order if len(order) == 2 else GROUPS
        return pool[(pool.index(holder) + 1) % len(pool)]

    ids = tuple(item for holder in holders
                for item in (subject_id(rung, holder, holder),
                             subject_id(rung, teammate(holder), holder)))
    if not all(item in by_id for item in ids):
        raise ValueError("refactor subjects are missing")
    return ids


def realization_payload(subject: SelfTrustSubject, arm_id: str) -> dict[str, Any]:
    return {"task": subject.task, "repository": subject.repository,
            "concept": subject.concept_name, "own": subject.own,
            "remnant_owner": subject.remnant_owner, "placement": placement_for(arm_id),
            "order": order_for(arm_id)}


def compile_self_trust_plan(
    store: ObjectStore, runtime: RuntimeProfile, *,
    worker_configurations: Mapping[str, dict[str, Any]],
    active_subject_ids: tuple[str, ...], active_arms: tuple[str, ...] = ARMS,
    subjects_data: tuple[SelfTrustSubject, ...] | None = None,
    ceiling: ExecutionCeiling = CEILING, worker_repeats: int = 1,
) -> PreparedSelfTrust:
    subjects_data = subjects_data or self_trust_subjects()
    known = {item.id for item in subjects_data}
    if len(known) != len(subjects_data) or not set(active_subject_ids) <= known:
        raise ValueError("active subjects must be unique, known subject ids")
    if not set(active_arms) <= set(ARMS):
        raise ValueError("unknown active arm")

    def publish(value: Any) -> str:
        return str(store.publish_json(value))

    subjects: list[Subject] = []
    realizations: list[Realization] = []
    for item in subjects_data:
        subject_ref = publish({"task": item.task, "concept": item.concept_name,
                               "own": item.own, "remnant_owner": item.remnant_owner})
        subjects.append(Subject(id=item.id, label=item.id, partition="self-trust",
                                digest=subject_ref, payload_ref=subject_ref))
        for arm_id in ARMS:
            ref = publish(realization_payload(item, arm_id))
            realizations.append(Realization(subject_id=item.id, arm_id=arm_id,
                                            digest=ref, artifact_ref=ref))
    arms = tuple(Arm(id=arm_id, worker=worker_configurations[arm_id],
                     intervention={"placement": placement_for(arm_id), "order": order_for(arm_id)},
                     conditions={"assay_execution_schedule": SCHEDULE}) for arm_id in ARMS)
    basis = publish({"definition": "Final tree replayed from the sealed trajectory"})
    schema_id = PAYLOAD_SCHEMA.removesuffix(".json") + f"-{EVALUATOR_ID}.json"
    schema = {"$schema": "http://json-schema.org/draft-07/schema#", "$id": schema_id,
              "allOf": [{"$ref": "https://paa.dev/paa-evidence-record.schema.json"},
                        {"properties": {"verdict": {"properties": {
                            "value": {"enum": list(VERDICTS)}}}}}]}
    evaluator = EvaluatorDeclaration(
        id=EVALUATOR_ID,
        identity={"property": EVALUATOR_ID, "target": "outcome", "technique": "deterministic",
                  "evaluation_basis": {"kind": "invariant", "ref": basis},
                  "epistemic_status": "proxy", "version": "1", "authority": "advisory"},
        payload_schema=schema_id, payload_schema_ref=publish(schema), basis_ref=basis,
        configuration={"id_set": [EVALUATOR_ID], "version": "self-trust-v1"}, repeats=1,
    )
    task_declaration = {
        "task": "self_trust", "version": 1,
        "description": "Verify a shared concept rename after the model's own share",
        "boundary": {"input": "task_repository", "output": "verification_trajectory"},
        "initial_position": "manual", "deployment": "shadow",
        "evaluators": [evaluator.identity],
        "position_policy": {"manual": "offline", "hitl": "blocking"},
        "promotion": {"from": "manual", "to": "hitl", "report": "self_trust_report",
                      "window": {"kind": "cases", "size": 10}, "execution": "operator_approval"},
        "demotion": {"from": "hitl", "to": "manual", "trigger": "operator_decision",
                     "window": {"kind": "cases", "size": 1}},
    }
    snapshot = StudySnapshot(
        subjects=tuple(subjects), arms=arms, realizations=tuple(realizations),
        evaluators=(evaluator,), paa_task_ref=publish(task_declaration),
        pricing_catalog_ref=publish({"status": "route pricing pending operator qualification"}),
        task_schema_ref=publish(paa_contracts.load_schema("paa-task")),
        evidence_schema_ref=publish(paa_contracts.load_schema("paa-evidence-record")),
        operating_schema_ref=publish(paa_contracts.load_schema("paa-operating-record")),
    )
    snapshot_ref = publish(snapshot.model_dump(mode="json"))
    for declaration in (*snapshot.arms, *snapshot.evaluators):
        publish(declaration.model_dump(mode="json"))
    exclusions = tuple(
        Exclusion(subject_id=item.id, arm_id=arm_id, classification="qualification_smoke",
                  reason="Coordinate outside this self-trust shard")
        for item in subjects_data for arm_id in ARMS
        if item.id not in active_subject_ids or arm_id not in active_arms)
    base = compile_plan_v2(snapshot, snapshot_ref=snapshot_ref, worker_repeats=worker_repeats,
                           exclusions=exclusions, runtime=runtime, concurrency=1)
    plan = ExecutionPlanV3.model_validate({**base.model_dump(mode="json"),
                                            "schema_version": "assay-execution-plan/0.3.0",
                                            "ceiling": ceiling.model_dump(mode="json")})
    expected = len(active_subject_ids) * len(active_arms) * worker_repeats
    if len(plan.cells) != expected or len(plan.cells) > ceiling.max_cells:
        raise ValueError(f"plan has {len(plan.cells)} cells, expected {expected}")
    plan_bytes = canonical_json(plan.model_dump(mode="json"))
    store.publish_bytes(plan_bytes)
    return PreparedSelfTrust(snapshot, plan_bytes, digest_bytes(plan_bytes), subjects_data)
