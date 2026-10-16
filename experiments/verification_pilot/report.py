"""Section 11 reporting over verified pilot records.

The shared engine owns subject-paired arm comparisons. H1 and H4 are pilot
statistics because their comparisons do not fit its paired-arm report shape.
"""

from __future__ import annotations

import base64
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from statistics import fmean
from typing import Any

from assay.models import (
    ReportConfig,
    RunManifest,
    StatisticalProfile,
    StudySnapshot,
    parse_execution_plan,
)
from assay.report_engine import build_report, exact_sign_test, persist_report
from assay.store import ObjectStore
from assay.verify import verify_manifest
from verification_pilot.evaluation import NOT_APPLICABLE, REPORT_CATEGORIES
from verification_pilot.migrations import GROUPS, MIGRATIONS


@dataclass(frozen=True, slots=True)
class Observation:
    model: str
    subject: str
    migration: str
    group: str
    rotation: int
    block_position: int
    arm: str
    evaluator_id: str
    value: str


def _read(store: ObjectStore, ref: str) -> dict[str, Any]:
    value = json.loads(store.read_bytes(ref))
    if not isinstance(value, dict):
        raise ValueError(f"expected object at {ref}")
    return value


def _position(group: str, rotation: int) -> int:
    return (GROUPS.index(group) - rotation) % len(GROUPS) + 1


def verified_observations(
    store: ObjectStore, manifest_refs: Sequence[str], model: str
) -> tuple[Observation, ...]:
    """Use only terminal verdicts from fully verified manifests on one route."""
    rows: list[Observation] = []
    runtime: bytes | None = None
    seen: set[tuple[str, str, str]] = set()
    for ref in manifest_refs:
        failures = [f for f in verify_manifest(store, ref) if f.code != "incomplete_run"]
        if failures:
            raise ValueError(f"invalid manifest {ref}: {failures[0].code}")
        manifest = RunManifest.model_validate(_read(store, ref))
        plan = parse_execution_plan(_read(store, manifest.plan_ref))
        snapshot = StudySnapshot.model_validate(_read(store, plan.snapshot_ref))
        identity = json.dumps(plan.runtime.model_dump(mode="json"), sort_keys=True).encode()  # type: ignore[union-attr]
        if runtime is not None and identity != runtime:
            raise ValueError("run compatibility drift across selected manifests")
        runtime = identity
        subjects = {s.id: _read(store, s.payload_ref) for s in snapshot.subjects}
        cells = {cell.id: cell for cell in plan.cells}
        for coordinate in plan.evaluations:
            record_ref = manifest.evaluation_records.get(coordinate.id)
            if record_ref is None:
                continue
            record = _read(store, record_ref)
            if "verdict" not in record:
                continue
            cell = cells[coordinate.cell_id]
            payload = subjects[cell.subject_id]
            value = record["verdict"]["value"]
            if not isinstance(value, str):
                raise ValueError("pilot verdict must be a declared category")
            key = (cell.subject_id, cell.arm_id, coordinate.evaluator_id)
            if key in seen:
                raise ValueError("duplicate subject/arm/evaluator across manifests")
            seen.add(key)
            group = str(payload["ownership_group"])
            rotation = int(payload["rotation"])
            rows.append(Observation(
                model, cell.subject_id, str(payload["migration"]), group,
                rotation, _position(group, rotation), cell.arm_id,
                coordinate.evaluator_id, value,
            ))
    return tuple(rows)


def h1_ownership_gap(rows: Iterable[Observation], arm: str) -> dict[str, Any]:
    """One-sample, two-sided exact sign test of T1 ownership gap against zero."""
    selected = [float(r.value) for r in rows if r.arm == arm
                and r.evaluator_id == "t1_ownership_gap" and r.value != NOT_APPLICABLE]
    improved = sum(value > 0 for value in selected)
    regressed = sum(value < 0 for value in selected)
    return {
        "hypothesis": "H1", "arm": arm, "n": len(selected),
        "improved": improved, "regressed": regressed,
        "ties": len(selected) - improved - regressed,
        "mean_gap": fmean(selected) if selected else None,
        "test": "one_sample_exact_sign_against_zero",
        "p_value": exact_sign_test(improved, regressed) if selected else None,
        "alpha": 0.05,
    }


def h4_own_vs_teammate(
    rows: Iterable[Observation], arm: str, *, own_group: str,
    evaluator_id: str = "t1_remnant_inspected",
) -> dict[str, Any]:
    """Compare different subjects within one arm, matched by migration.

    Rotations are averaged within migration/group. The own group is supplied by
    the caller's declared ownership assignment, never inferred from a verdict.
    With four migrations this remains descriptive: the engine's floor is ten.
    """
    if own_group not in GROUPS:
        raise ValueError("unknown own ownership group")
    buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        if row.arm == arm and row.evaluator_id == evaluator_id and row.value != NOT_APPLICABLE:
            buckets[(row.migration, row.group)].append(float(row.value))
    pairs: list[dict[str, Any]] = []
    differences: list[float] = []
    for migration in sorted({migration for migration, _ in buckets}):
        own = buckets.get((migration, own_group), [])
        teammates = [value for (name, group), values in buckets.items()
                     if name == migration and group != own_group for value in values]
        if own and teammates:
            pairs.append({"migration": migration, "own": fmean(own),
                          "teammate": fmean(teammates)})
            differences.append(fmean(own) - fmean(teammates))
    return {"hypothesis": "H4", "arm": arm, "own_group": own_group,
            "evaluator_id": evaluator_id, "n": len(pairs), "pairs": pairs,
            "mean_difference": fmean(differences) if differences else None,
            "p_value": None, "engine_p_value": None,
            "decision": "descriptive_only"}


def _record_refs(
    store: ObjectStore, manifest_refs: Sequence[str], evaluator_id: str
) -> tuple[str, ...]:
    refs: list[str] = []
    for ref in manifest_refs:
        manifest = RunManifest.model_validate(_read(store, ref))
        plan = parse_execution_plan(_read(store, manifest.plan_ref))
        refs.extend(manifest.evaluation_records[coordinate.id]
                    for coordinate in plan.evaluations
                    if coordinate.evaluator_id == evaluator_id
                    and coordinate.id in manifest.evaluation_records)
    return tuple(sorted(refs))


def paired_config(
    store: ObjectStore, manifest_refs: Sequence[str], *, evaluator_id: str,
    reference_arm: str, candidate_arm: str, seed: int = 11,
) -> ReportConfig:
    """Pin the existing 0.1.0 engine and paired-v2 profile for H2/H3."""
    if evaluator_id not in REPORT_CATEGORIES:
        raise ValueError(f"unknown pilot evaluator: {evaluator_id}")
    return ReportConfig(
        manifest_refs=tuple(manifest_refs),
        record_refs=_record_refs(store, manifest_refs, evaluator_id),
        reference_arm=reference_arm, candidates=(candidate_arm,),
        evaluator_id=evaluator_id, metric="ordinal",
        evaluator_repeat_aggregation="median", worker_repeat_aggregation="median",
        categories=REPORT_CATEGORIES[evaluator_id],
        statistical_profile=StatisticalProfile(name="paired-v2", seed=seed,
                                               bootstrap_samples=1000, alpha=0.05),
        engine_version="0.1.0",
    )


def evaluator_tables(rows: Iterable[Observation]) -> list[dict[str, Any]]:
    counts: Counter[tuple[str, str, str, str, int, str, str]] = Counter(
        (r.model, r.arm, r.evaluator_id.split("_", 1)[0], r.group,
         r.block_position, r.evaluator_id, r.value) for r in rows
    )
    return [{"model": model, "arm": arm, "turn": turn, "remnant_location": group,
             "block_position": position, "evaluator_id": evaluator, "value": value,
             "count": count}
            for (model, arm, turn, group, position, evaluator, value), count
            in sorted(counts.items())]


def escalation_chart(rows: Iterable[Observation]) -> list[dict[str, Any]]:
    measures = {"saw_remnant_by", "remnant_inspected", "ran_tests", "test_masked",
                "silent_fix", "false_claim_case", "flip"}
    selected: Counter[tuple[str, str, str, str, str]] = Counter(
        (r.model, r.arm, r.evaluator_id.split("_", 1)[0],
         r.evaluator_id.split("_", 1)[1], r.value)
        for r in rows if r.evaluator_id.split("_", 1)[1] in measures
    )
    return [{"model": model, "arm": arm, "turn": turn, "measure": measure,
             "value": value, "count": count}
            for (model, arm, turn, measure, value), count in sorted(selected.items())]


def ceiling_effect(
    store: ObjectStore, manifest_refs: Sequence[str], model: str
) -> list[dict[str, Any]]:
    """Share whose first T1 inspection is a repository-wide symbol search."""
    totals: Counter[str] = Counter()
    wide: Counter[str] = Counter()
    old_by_migration = {migration.name: migration.old_symbol for migration in MIGRATIONS}
    for ref in manifest_refs:
        manifest = RunManifest.model_validate(_read(store, ref))
        plan = parse_execution_plan(_read(store, manifest.plan_ref))
        snapshot = StudySnapshot.model_validate(_read(store, plan.snapshot_ref))
        subjects = {subject.id: _read(store, subject.payload_ref) for subject in snapshot.subjects}
        for cell in plan.cells:
            outcome_ref = manifest.execution_records.get(cell.id)
            if outcome_ref is None:
                continue
            outcome = _read(store, outcome_ref)
            if outcome.get("status") != "succeeded" or not outcome.get("output_ref"):
                continue
            output = _read(store, outcome["output_ref"])
            raw = _read(store, output["raw_trajectory_ref"])
            trajectory = json.loads(base64.b64decode(raw["content_base64"]))
            turns = trajectory.get("turns", [])
            if not turns:
                continue
            totals[cell.arm_id] += 1
            inspections = [call for call in turns[0].get("tool_calls", [])
                           if call.get("name") in ("read_file", "search_files")]
            if inspections:
                first = inspections[0]
                args = first.get("arguments", {})
                symbol = old_by_migration[subjects[cell.subject_id]["migration"]]
                if (first.get("name") == "search_files"
                        and args.get("scope") in ("", ".", "./")
                        and symbol in str(args.get("query", ""))):
                    wide[cell.arm_id] += 1
    return [{"model": model, "arm": arm, "repository_wide_first": wide[arm],
             "n": count, "share": wide[arm] / count}
            for arm, count in sorted(totals.items())]


def power_statement() -> dict[str, str]:
    return {
        "H1": "48 paired observations per model in the Tier 1 grid; one-sample sign test by arm.",
        "H2": "48 paired observations per model in the Tier 1 grid.",
        "H3": "12 of 16 base subjects valid in both arms; deferred Tier 2 data required.",
        "H4": ("4 migration-matched pairs; below the engine's ten-subject "
               "inference floor. No engine p-value."),
    }


def model_report(
    store: ObjectStore, manifest_refs: Sequence[str], *, model: str,
    own_group: str, tier2_refs: Sequence[str] = (),
) -> dict[str, Any]:
    """Assemble per-model results; persist each engine comparison separately."""
    rows = verified_observations(store, manifest_refs, model)
    h2_config = paired_config(store, manifest_refs, evaluator_id="t1_ownership_gap",
                              reference_arm="t1-native", candidate_arm="t1-quoted")
    h2 = build_report(store, h2_config)
    h2_ref = str(persist_report(store, h2_config))
    result: dict[str, Any] = {
        "model": model, "manifest_refs": list(manifest_refs),
        "H1": {arm: h1_ownership_gap(rows, arm) for arm in ("t1-native", "t1-quoted")},
        "H2": {"report_ref": h2_ref, "comparison": h2["comparisons"][0]},
        "H4": {arm: h4_own_vs_teammate(rows, arm, own_group=own_group)
               for arm in ("t1-native", "t1-quoted")},
        "tables": evaluator_tables(rows), "escalation_chart": escalation_chart(rows),
        "ceiling_effect": ceiling_effect(store, manifest_refs, model),
        "cost": h2["costs"], "power": power_statement(),
    }
    if tier2_refs:
        tier2_rows = verified_observations(store, tier2_refs, model)
        config = paired_config(store, tier2_refs, evaluator_id="t2_saw_remnant_by",
                               reference_arm="t2-native", candidate_arm="t2-quoted")
        report = build_report(store, config)
        result["H3"] = {"report_ref": str(persist_report(store, config)),
                        "comparison": report["comparisons"][0]}
        result["tables"].extend(evaluator_tables(tier2_rows))
    else:
        result["H3"] = {"status": "in_progress", "reason": "Tier 2 deferred"}
    return result


def cross_model_table(reports: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Display route results without pooling incompatible manifests."""
    return [{"model": model, "H1": report["H1"], "H2": report["H2"],
             "H3": report["H3"], "H4": report["H4"],
             "ceiling_effect": report["ceiling_effect"], "cost": report["cost"]}
            for model, report in sorted(reports.items())]
