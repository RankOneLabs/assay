"""Deterministic paired scalar reporting with subject-level resampling."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from statistics import fmean, pstdev

import numpy as np


@dataclass(frozen=True, slots=True)
class PairedComparison:
    candidate: str
    reference: str
    common_subjects: tuple[str, ...]
    excluded_subjects: tuple[str, ...]
    effect: float | None
    confidence_interval: tuple[float, float] | None
    p_value: float | None
    adjusted_p_value: float | None
    decision: str
    within_subject_spread: float | None


def _holm(p_values: list[float]) -> list[float]:
    order = sorted(range(len(p_values)), key=p_values.__getitem__)
    adjusted = [0.0] * len(p_values)
    running = 0.0
    total = len(p_values)
    for rank, index in enumerate(order):
        running = max(running, min(1.0, (total - rank) * p_values[index]))
        adjusted[index] = running
    return adjusted


def bootstrap_paired(
    deltas: list[float], *, seed: int, samples: int
) -> tuple[tuple[float, float], float]:
    """Compute paired-v1 arithmetic, independently of the report's n>=10 gate."""
    if not deltas or samples < 100 or seed < 0 or not all(math.isfinite(x) for x in deltas):
        raise ValueError("finite nonempty deltas, samples>=100 and seed>=0 required")
    values = np.asarray(deltas, dtype=float)
    rng = np.random.default_rng(seed)
    centered = values - values.mean()
    # Bound the temporary index/value matrix for large subject sets.
    batch = max(1, 1_000_000 // len(values))
    observed = np.concatenate([
        rng.choice(values, size=(min(batch, samples - start), len(values))).mean(axis=1)
        for start in range(0, samples, batch)
    ])
    null = np.concatenate([
        rng.choice(centered, size=(min(batch, samples - start), len(values))).mean(axis=1)
        for start in range(0, samples, batch)
    ])
    interval = (float(np.quantile(observed, .025)), float(np.quantile(observed, .975)))
    p_value = (1 + int(np.count_nonzero(np.abs(null) >= abs(values.mean())))) / (samples + 1)
    return interval, p_value


def compare_scalar(
    rows: list[tuple[str, str, int, int, float]],
    *,
    reference: str,
    candidates: list[str],
    seed: int = 0,
    bootstrap_samples: int = 10_000,
    alpha: float = 0.05,
) -> tuple[PairedComparison, ...]:
    """Aggregate evaluator repeats, then worker repeats, then pair subjects."""
    if alpha != 0.05 or bootstrap_samples < 100 or seed < 0:
        raise ValueError("paired-v1 requires alpha=.05, samples>=100 and seed>=0")
    if reference in candidates or len(candidates) != len(set(candidates)):
        raise ValueError("candidate family must be unique and exclude reference")
    evaluator_groups: dict[tuple[str, str, int], list[float]] = defaultdict(list)
    seen = set()
    for subject, arm, worker_repeat, evaluator_repeat, value in rows:
        coordinate = (subject, arm, worker_repeat, evaluator_repeat)
        if coordinate in seen:
            raise ValueError(f"duplicate evaluation coordinate {coordinate}")
        if isinstance(value, bool) or not math.isfinite(value):
            raise ValueError("scalar verdicts must be finite numbers")
        seen.add(coordinate)
        evaluator_groups[(subject, arm, worker_repeat)].append(value)
    workers: dict[tuple[str, str], list[float]] = defaultdict(list)
    for (subject, arm, _repeat), values in evaluator_groups.items():
        workers[(subject, arm)].append(fmean(values))
    subject_values = {key: fmean(values) for key, values in workers.items()}
    interim: list[tuple[PairedComparison, float | None]] = []
    for candidate in sorted(candidates):
        all_subjects = {s for s, a in subject_values if a in (reference, candidate)}
        common = tuple(
            sorted(
                subject
                for subject in all_subjects
                if (subject, reference) in subject_values and (subject, candidate) in subject_values
            )
        )
        excluded = tuple(sorted(all_subjects - set(common)))
        deltas = np.array(
            [
                subject_values[(subject, candidate)] - subject_values[(subject, reference)]
                for subject in common
            ]
        )
        effect = float(deltas.mean()) if len(deltas) else None
        spreads = [
            pstdev(workers[(subject, arm)]) for subject in common for arm in (reference, candidate)
        ]
        spread = fmean(spreads) if spreads else None
        interval: tuple[float, float] | None = None
        p_value: float | None = None
        decision = "descriptive_only"
        if len(deltas) >= 10:
            interval, p_value = bootstrap_paired(
                deltas.tolist(), seed=seed, samples=bootstrap_samples
            )
        interim.append(
            (
                PairedComparison(
                    candidate,
                    reference,
                    common,
                    excluded,
                    effect,
                    interval,
                    p_value,
                    None,
                    decision,
                    spread,
                ),
                p_value,
            )
        )
    numeric = [value if value is not None else 1.0 for _result, value in interim]
    adjusted_values = iter(_holm(numeric))
    results = []
    for result, p_value in interim:
        family_adjusted = next(adjusted_values)
        adjusted = family_adjusted if p_value is not None else None
        decision = (
            "different"
            if adjusted is not None and adjusted < alpha
            else ("no_detected_difference" if adjusted is not None else "descriptive_only")
        )
        results.append(
            PairedComparison(
                result.candidate,
                result.reference,
                result.common_subjects,
                result.excluded_subjects,
                result.effect,
                result.confidence_interval,
                result.p_value,
                adjusted,
                decision,
                result.within_subject_spread,
            )
        )
    return tuple(results)
