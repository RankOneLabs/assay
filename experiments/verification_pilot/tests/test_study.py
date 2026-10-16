"""The declared snapshot covers rotations, tiers, and compatible shards."""

import json
from pathlib import Path

from assay.canonical import canonical_json
from assay.models import ExecutionOutcome, ExecutionPlanV3, RuntimeProfile
from assay.store import ObjectStore
from verification_pilot.arms import ALL_ARMS, TIER_1_ARMS, TIER_2_ARMS
from verification_pilot.study import FINAL_CEILING, compile_pilot_plan, pilot_subjects


def _runtime(store: ObjectStore) -> RuntimeProfile:
    return RuntimeProfile(id="scripted", version="1",
                          configuration_ref=str(store.publish_json({"scripted": True})))


def test_rotated_snapshot_and_all_tier_exclusions(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    subjects = pilot_subjects()
    prepared = compile_pilot_plan(store, _runtime(store),
                                  worker_configuration={"id": "scripted", "version": "1"},
                                  subjects_data=subjects)
    plan = ExecutionPlanV3.model_validate_json(prepared.plan_bytes)
    assert len(subjects) == 48
    assert len({(s.migration.name, s.group) for s in subjects}) == 16
    assert all({s.rotation for s in subjects if s.migration.name == migration
                and s.group == group} == {0, 1, 2}
               for migration, group in {(s.migration.name, s.group) for s in subjects})
    assert len(prepared.snapshot.realizations) == 48 * len(ALL_ARMS)
    assert prepared.snapshot.consistent_grid() == prepared.snapshot
    assert len({(r.subject_id, r.arm_id) for r in prepared.snapshot.realizations}) == 288
    assert len(plan.cells) == 48 * 2 * 1 == 96
    assert plan.worker_repeats == 1
    assert set(a.id for a in prepared.snapshot.arms) == set(ALL_ARMS)
    assert len(plan.exclusions) == 48 * 4
    assert {e.arm_id for e in plan.exclusions} == set(ALL_ARMS) - set(TIER_1_ARMS)
    assert all(a.conditions["assay_execution_schedule"] == "subject-rotated-v1"
               for a in prepared.snapshot.arms)
    assert plan.ceiling == FINAL_CEILING
    payloads = [json.loads(store.read_bytes(s.payload_ref)) for s in prepared.snapshot.subjects]
    assert {p["rotation"] for p in payloads} == {0, 1, 2}
    cell = plan.cells[0]
    outcome = ExecutionOutcome(
        run_id="test", plan_ref=prepared.authorization,
        started_at="2026-01-01T00:00:00Z", completed_at="2026-01-01T00:00:01Z",
        coordinate=cell, status="succeeded", input_ref=cell.realization_ref,
        output_ref=cell.realization_ref,
    )
    assert outcome.consistent_status() == outcome


def test_tier_shards_keep_report_compatibility_fields(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    runtime = _runtime(store)
    worker = {"id": "scripted", "version": "1"}
    subjects = pilot_subjects()
    tier1 = compile_pilot_plan(store, runtime, worker_configuration=worker,
                               subjects_data=subjects)
    tier2 = compile_pilot_plan(store, runtime, worker_configuration=worker,
                               subjects_data=subjects, active_arms=TIER_2_ARMS)
    one = ExecutionPlanV3.model_validate_json(tier1.plan_bytes)
    two = ExecutionPlanV3.model_validate_json(tier2.plan_bytes)
    assert tier1.snapshot == tier2.snapshot
    assert one.snapshot_ref == two.snapshot_ref
    assert one.runtime == two.runtime
    assert one.worker_repeats == two.worker_repeats
    assert one.concurrency == two.concurrency
    assert one.ceiling == two.ceiling
    assert one.schema_version == two.schema_version
    assert one.assay_version == two.assay_version
    assert one.exclusions != two.exclusions
    assert {cell.arm_id for cell in two.cells} == set(TIER_2_ARMS)

    def fingerprint(plan: ExecutionPlanV3) -> bytes:
        snapshot = tier1.snapshot
        return canonical_json({
            "task_ref": snapshot.paa_task_ref,
            "scope": snapshot.paa_scope,
            "task_schema_ref": snapshot.task_schema_ref,
            "evidence_schema_ref": snapshot.evidence_schema_ref,
            "operating_schema_ref": snapshot.operating_schema_ref,
            "pricing_catalog_ref": snapshot.pricing_catalog_ref,
            "pricing_assumptions": snapshot.pricing_assumptions,
            "worker_repeats": plan.worker_repeats,
            "preparation_mode": plan.preparation_mode,
            "concurrency": plan.concurrency,
            "runtime": plan.runtime.model_dump(mode="json"),
            "assay_version": plan.assay_version,
            "schema_version": plan.schema_version,
            "ceiling": plan.ceiling.model_dump(mode="json"),
        })

    assert fingerprint(one) == fingerprint(two)
