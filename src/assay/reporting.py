"""Deterministic paired scalar reporting with subject-level resampling."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from statistics import fmean, pstdev

from assay.statistical_limits import validate_sampling


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


class _IndexStream:
    """paired-v2 SHA-256 counter stream with unbiased uint64 rejection sampling."""

    def __init__(self, seed: int, domain: bytes) -> None:
        self.prefix = b"assay/paired-v2\0" + str(seed).encode("ascii") + b"\0" + domain + b"\0"
        self.counter = 0
        self.words: list[int] = []

    def index(self, size: int) -> int:
        if not 0 < size <= 2**64:
            raise ValueError("sample population must fit uint64")
        limit = 2**64 - 2**64 % size
        while True:
            if not self.words:
                block = sha256(self.prefix + self.counter.to_bytes(16, "big")).digest()
                self.counter += 1
                self.words = [int.from_bytes(block[i:i + 8], "big") for i in (24, 16, 8, 0)]
            word = self.words.pop()
            if word < limit:
                return word % size


def _integer_values(values: list[float]) -> tuple[list[int], int]:
    ratios = [float(value).as_integer_ratio() for value in values]
    denominator = max(d for _, d in ratios)
    return [n * (denominator // d) for n, d in ratios], denominator


def paired_effect(deltas: list[float]) -> float | None:
    """Exactly sum binary64 inputs, then round the rational mean once."""
    if not deltas:
        return None
    values, denominator = _integer_values(deltas)
    return float(Fraction(sum(values), len(values) * denominator))


def bootstrap_paired(
    deltas: list[float], *, seed: int, samples: int
) -> tuple[tuple[float, float], float]:
    """paired-v2 exact resampling arithmetic; see docs/statistical-profile.md."""
    validate_sampling(seed=seed, samples=samples)
    if not deltas or not all(math.isfinite(x) for x in deltas):
        raise ValueError("finite nonempty deltas required")
    values, denominator = _integer_values(deltas)
    n, total = len(values), sum(values)
    observed_stream = _IndexStream(seed, b"observed")
    null_stream = _IndexStream(seed, b"null")
    observed = sorted(
        sum(values[observed_stream.index(n)] for _ in range(n)) for _ in range(samples)
    )
    extreme = sum(
        abs(sum(values[null_stream.index(n)] for _ in range(n)) - total) >= abs(total)
        for _ in range(samples)
    )

    def quantile(numerator: int) -> float:
        index, remainder = divmod((samples - 1) * numerator, 40)
        upper = min(index + 1, samples - 1)
        return float(Fraction(
            observed[index] * (40 - remainder) + observed[upper] * remainder,
            40 * n * denominator,
        ))

    return (quantile(1), quantile(39)), float(Fraction(1 + extreme, samples + 1))


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
    validate_sampling(seed=seed, samples=bootstrap_samples)
    if alpha != 0.05:
        raise ValueError("paired-v2 requires alpha=.05")
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
        deltas = [
            subject_values[(subject, candidate)] - subject_values[(subject, reference)]
            for subject in common
        ]
        effect = paired_effect(deltas)
        spreads = [
            pstdev(workers[(subject, arm)]) for subject in common for arm in (reference, candidate)
        ]
        spread = fmean(spreads) if spreads else None
        interval: tuple[float, float] | None = None
        p_value: float | None = None
        decision = "descriptive_only"
        if len(deltas) >= 10:
            interval, p_value = bootstrap_paired(
                deltas, seed=seed, samples=bootstrap_samples
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
