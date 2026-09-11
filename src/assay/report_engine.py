"""Deterministic reports from an exact selection of verified immutable records."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from decimal import Decimal
from statistics import fmean, median, pstdev
from typing import Any

from assay._version import __version__
from assay.canonical import canonical_json, digest_bytes
from assay.models import ExecutionPlan, ReportConfig, RunManifest, StudySnapshot
from assay.reporting import _holm, bootstrap_paired, paired_effect
from assay.store import ObjectRef, ObjectStore, verification_session


class ReportError(ValueError):
    """The selected artifacts cannot support the requested report."""


def exact_sign_test(improved: int, regressed: int) -> float:
    """Two-sided binomial test with p=.5; ties excluded from denominator.

    https://www.itl.nist.gov/div898/software/dataplot/refman1/auxillar/signtest.htm
    Also exact McNemar when directions compare paired correctness.
    """
    if improved < 0 or regressed < 0:
        raise ReportError("sign counts cannot be negative")
    n = improved + regressed
    return float(
        min(1.0, 2 * sum(math.comb(n, i) for i in range(min(improved, regressed) + 1)) / 2**n)
    )


def _aggregate(values: list[Any], rule: str, config: ReportConfig, *, mapped: bool = False) -> Any:
    numeric = config.metric == "scalar" or config.ordinal_mapping is not None
    if numeric:
        nums = [
            float(config.ordinal_mapping[str(v)])
            if config.ordinal_mapping is not None and not mapped
            else float(v)
            for v in values
        ]
        if not all(math.isfinite(v) for v in nums):
            raise ReportError("nonfinite verdict")
        if rule == "mean":
            return fmean(nums)
        if rule == "median":
            return float(median(nums))
        raise ReportError("numeric aggregation requires mean or median")
    if any(v not in config.categories for v in values):
        raise ReportError("unknown verdict category")
    if rule == "median" and config.metric == "ordinal":
        return sorted(values, key=config.categories.index)[(len(values) - 1) // 2]
    if rule == "majority":
        counts = Counter(values)
        return min(counts, key=lambda v: (-counts[v], config.categories.index(v)))
    raise ReportError("categorical aggregation requires majority or ordinal lower median")


def _read(store: ObjectStore, ref: str) -> Any:
    return json.loads(store.read_bytes(ref))


def classification_metrics(
    truth: list[str], predictions: list[str], categories: tuple[str, ...], positive: str | None
) -> dict[str, Any]:
    matrix = [[0 for _ in categories] for _ in categories]
    for actual, predicted in zip(truth, predictions, strict=True):
        matrix[categories.index(actual)][categories.index(predicted)] += 1
    result: dict[str, Any] = {
        "labels": list(categories),
        "confusion": matrix,
        "accuracy": sum(a == b for a, b in zip(truth, predictions, strict=True)) / len(truth)
        if truth
        else None,
    }
    if positive is not None:
        i = categories.index(positive)
        tp, actual_count, predicted_count = (
            matrix[i][i],
            sum(matrix[i]),
            sum(row[i] for row in matrix),
        )
        result.update(
            precision=tp / predicted_count if predicted_count else None,
            recall=tp / actual_count if actual_count else None,
        )
    return result


def build_report(store: ObjectStore, config: ReportConfig) -> dict[str, Any]:
    from assay.verify import verify_manifest

    store = verification_session(store)
    config = ReportConfig.model_validate(config.model_dump(mode="json"))
    if config.engine_version != __version__:
        raise ReportError("unsupported report engine version")
    arms = {config.reference_arm, *config.candidates}
    values: dict[tuple[str, str], Any] = {}
    labels: dict[str, str] = {}
    label_digests: dict[str, str] = {}
    subject_declarations: dict[str, bytes] = {}
    truth: dict[str, str] = {}
    declarations: dict[str, bytes] = {}
    expected_records: set[str] = set()
    missing: dict[str, Counter[str]] = {a: Counter() for a in sorted(arms)}
    exclusions: list[Any] = []
    disagreement: list[Any] = []
    spread: list[Any] = []
    seen_subject_arms: set[tuple[str, str]] = set()
    operating_refs: list[str] = []
    numeric = config.metric == "scalar" or config.ordinal_mapping is not None
    for manifest_ref in sorted(config.manifest_refs):
        problems = verify_manifest(store, manifest_ref)
        if problems:
            raise ReportError(f"invalid manifest: {problems[0].code}")
        manifest = RunManifest.model_validate(_read(store, manifest_ref))
        if manifest.status != "complete":
            raise ReportError("reports require complete manifests")
        plan = ExecutionPlan.model_validate(_read(store, manifest.plan_ref))
        snapshot = StudySnapshot.model_validate(_read(store, plan.snapshot_ref))
        evaluator = next((e for e in snapshot.evaluators if e.id == config.evaluator_id), None)
        if evaluator is None or not arms <= {a.id for a in snapshot.arms}:
            raise ReportError("report evaluator or arm absent from snapshot")
        for key, declaration in [
            ("evaluator:" + evaluator.id, evaluator),
            *(("arm:" + a.id, a) for a in snapshot.arms if a.id in arms),
        ]:
            encoded = canonical_json(declaration.model_dump(mode="json"))
            if key in declarations and declarations[key] != encoded:
                raise ReportError("declaration drift across runs")
            declarations[key] = encoded
        by_id = {s.id: s for s in snapshot.subjects}
        for subject in snapshot.subjects:
            declaration_bytes = canonical_json(subject.model_dump(mode="json"))
            if (
                subject.digest in subject_declarations
                and subject_declarations[subject.digest] != declaration_bytes
            ):
                raise ReportError("subject declaration drift for same digest")
            subject_declarations[subject.digest] = declaration_bytes
            if subject.label in label_digests and label_digests[subject.label] != subject.digest:
                raise ReportError("base-subject digest drift for same label")
            labels[subject.digest] = subject.label
            label_digests[subject.label] = subject.digest
            if config.metric == "classification":
                label = _read(store, subject.payload_ref).get(config.label_key)
                if label not in config.categories:
                    raise ReportError("missing or invalid reference label")
                truth[subject.digest] = label
        groups: dict[tuple[str, str], list[Any]] = defaultdict(list)
        required_workers: Counter[tuple[str, str]] = Counter()
        evals = defaultdict(list)
        for coord in plan.evaluations:
            if coord.evaluator_id == config.evaluator_id:
                evals[coord.cell_id].append(coord)
        for excluded in plan.exclusions:
            if excluded.arm_id in arms:
                exclusions.append(excluded.model_dump(mode="json") | {"manifest_ref": manifest_ref})
                missing[excluded.arm_id]["excluded_subjects"] += 1
        for cell in plan.cells:
            if cell.arm_id not in arms:
                continue
            group = (by_id[cell.subject_id].digest, cell.arm_id)
            required_workers[group] += 1
            outcome = _read(store, manifest.execution_records[cell.id])
            if outcome["status"] != "succeeded":
                missing[cell.arm_id]["execution_failures"] += 1
            verdicts = []
            for coord in evals[cell.id]:
                ref = manifest.evaluation_records.get(coord.id)
                if ref is None:
                    continue
                expected_records.add(ref)
                record = _read(store, ref)
                if "verdict" not in record:
                    missing[cell.arm_id]["evaluation_failures"] += 1
                    continue
                verdict = record["verdict"]["value"]
                if config.metric == "scalar" and (
                    isinstance(verdict, bool) or not isinstance(verdict, (int, float))
                ):
                    raise ReportError("nonnumeric scalar verdict")
                if config.metric != "scalar" and verdict not in config.categories:
                    raise ReportError("unknown verdict category")
                verdicts.append(verdict)
            if outcome["status"] == "succeeded" and len(verdicts) == evaluator.repeats:
                groups[group].append(
                    _aggregate(verdicts, config.evaluator_repeat_aggregation, config)
                )
                disagreement.append(
                    {
                        "subject": group[0],
                        "arm": group[1],
                        "worker_repeat": cell.worker_repeat,
                        "verdicts": verdicts,
                        "unique_verdicts": len(set(verdicts)),
                        "scalar_spread": pstdev(verdicts) if config.metric == "scalar" else None,
                    }
                )
        for group, required in sorted(required_workers.items()):
            if group in seen_subject_arms:
                raise ReportError("duplicate subject/arm across selected runs")
            seen_subject_arms.add(group)
            repeated = groups[group]
            if len(repeated) != required:
                missing[group[1]]["incomplete_subjects"] += 1
                continue
            values[group] = _aggregate(
                repeated, config.worker_repeat_aggregation, config, mapped=True
            )
            spread.append(
                {
                    "subject": group[0],
                    "arm": group[1],
                    "values": repeated,
                    "scalar_spread": pstdev(repeated) if numeric else None,
                }
            )
        operating_refs.extend(manifest.operating_records.values())
    if expected_records != set(config.record_refs):
        raise ReportError("record selection differs from selected runs' evaluator records")
    comparisons: list[dict[str, Any]] = []
    profile = config.statistical_profile
    for candidate in sorted(config.candidates):
        common = sorted(
            s for s in labels if (s, candidate) in values and (s, config.reference_arm) in values
        )
        result: dict[str, Any] = {
            "candidate": candidate,
            "reference": config.reference_arm,
            "common_subjects": common,
            "common_subjects_ref": digest_bytes(canonical_json(common)),
            "non_common_subjects": sorted(set(labels) - set(common)),
            "n": len(common),
            "p_value": None,
            "confidence_interval": None,
            "interval_adjustment": "unadjusted",
        }
        left = [values[(s, config.reference_arm)] for s in common]
        right = [values[(s, candidate)] for s in common]
        if numeric:
            deltas = [float(b) - float(a) for a, b in zip(left, right, strict=True)]
            interval, p_value = (
                bootstrap_paired(deltas, seed=profile.seed, samples=profile.bootstrap_samples)
                if len(deltas) >= profile.min_subjects
                else (None, None)
            )
            result.update(
                effect=paired_effect(deltas),
                confidence_interval=list(interval) if interval is not None else None,
                p_value=p_value,
                between_subject_spread=pstdev(deltas) if deltas else None,
                test="centered_bootstrap",
            )
        else:
            if config.metric == "ordinal":
                directions = [
                    config.categories.index(b) - config.categories.index(a)
                    for a, b in zip(left, right, strict=True)
                ]
                result.update(
                    reference_distribution=dict(Counter(left)),
                    candidate_distribution=dict(Counter(right)),
                    test="exact_paired_sign",
                )
            else:
                directions = [
                    int(b == truth[s]) - int(a == truth[s])
                    for s, a, b in zip(common, left, right, strict=True)
                ]
                result.update(
                    reference_metrics=classification_metrics(
                        [truth[s] for s in common], left, config.categories, config.positive_label
                    ),
                    candidate_metrics=classification_metrics(
                        [truth[s] for s in common], right, config.categories, config.positive_label
                    ),
                    test="exact_mcnemar_correctness",
                )
            improved, regressed = sum(d > 0 for d in directions), sum(d < 0 for d in directions)
            result.update(
                improved=improved, regressed=regressed, ties=len(common) - improved - regressed
            )
            if len(common) >= 10:
                result["p_value"] = exact_sign_test(improved, regressed)
        comparisons.append(result)
    adjusted = _holm([r["p_value"] if r["p_value"] is not None else 1.0 for r in comparisons])
    for result, p in zip(comparisons, adjusted, strict=True):
        tested = result["p_value"] is not None
        result["adjusted_p_value"] = p if tested else None
        direction = result.get("effect", result.get("improved", 0) - result.get("regressed", 0))
        if numeric and config.scalar_direction == "lower_is_better" and direction is not None:
            direction = -direction
        result["decision"] = (
            "descriptive_only"
            if not tested
            else ("improved" if direction > 0 else "regressed")
            if p < 0.05
            else "no_detected_difference"
        )
    return {
        "record_schema": "assay-report/0.1.0",
        "config_ref": digest_bytes(canonical_json(config.model_dump(mode="json"))),
        "manifest_refs": sorted(config.manifest_refs),
        "record_refs": sorted(config.record_refs),
        "metric": config.metric,
        "scalar_direction": config.scalar_direction,
        "evaluator_id": config.evaluator_id,
        "evaluator_identity": json.loads(declarations["evaluator:" + config.evaluator_id])[
            "identity"
        ],
        "profile": profile.model_dump(mode="json"),
        "family_size": len(config.candidates),
        "missingness_policy": "complete_evaluator_and_worker_repeats",
        "missingness": {a: dict(v) for a, v in missing.items()},
        "exclusions": exclusions,
        "subject_labels": labels,
        "evaluator_disagreement": disagreement,
        "worker_spread": spread,
        "comparisons": comparisons,
        "operating_refs": sorted(operating_refs),
        "costs": summarize_operating(store, operating_refs),
        "verification_scope": (
            "integrity and completeness relative to supplied plan; no producer attestation"
        ),
    }


def persist_report(store: ObjectStore, config: ReportConfig) -> ObjectRef:
    report = build_report(store, config)
    store.publish_json(config.model_dump(mode="json"))
    for comparison in report["comparisons"]:
        store.publish_json(comparison["common_subjects"])
    return store.publish_json(report)


def summarize_operating(store: ObjectStore, refs: list[str]) -> dict[str, Any]:
    """Sum independent attempts using explicit producer measurement coverage."""
    seen: set[tuple[str, str]] = set()
    coverage: Counter[str] = Counter()
    totals: dict[str, Decimal] = defaultdict(Decimal)
    groups: dict[str, dict[str, Any]] = {}
    for ref in sorted(refs):
        record = _read(store, ref)
        details = [_read(store, source) for source in record["source_references"]]
        details = [d for d in details if isinstance(d, dict) and "coverage" in d and "attempt" in d]
        if len(details) != 1:
            raise ReportError("operating record lacks unambiguous attempt coverage")
        detail = details[0]
        key = (detail["run_id"], detail["attempt"])
        if key in seen:
            raise ReportError("overlapping operating attempt sources")
        seen.add(key)
        state = detail["coverage"]
        if state not in ("measured", "estimated", "unavailable", "mixed"):
            raise ReportError("unknown operating coverage")
        coverage[state] += 1
        stage, _subject, arm, *_rest = detail["attempt"].split(":")
        group = groups.setdefault(stage + ":" + arm, {"coverage_counts": {}, "amounts": {}})
        group["coverage_counts"][state] = group["coverage_counts"].get(state, 0) + 1
        price = record.get("price")
        if record.get("components"):
            raise ReportError("component operating prices are not supported")
        if price is None:
            if state != "unavailable":
                raise ReportError("missing price cannot claim measured or estimated coverage")
            continue
        if state == "unavailable":
            raise ReportError("priced attempt cannot claim unavailable coverage")
        currency = price["currency"]
        amount = Decimal(str(price["amount"]))
        totals[currency] += amount
        group["amounts"][currency] = float(Decimal(str(group["amounts"].get(currency, 0))) + amount)
    status = next(iter(coverage)) if len(coverage) == 1 else "mixed" if coverage else "unavailable"
    return {
        "coverage": status,
        "coverage_counts": dict(coverage),
        "amounts": {c: float(v) for c, v in totals.items()},
        "by_stage_arm": groups,
        "attempts": len(seen),
    }
