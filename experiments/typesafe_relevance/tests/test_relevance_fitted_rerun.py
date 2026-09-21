from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from typesafe_relevance.fitted_rerun import build_fitted_report


@pytest.fixture(autouse=True)
def _require_run_receipts(run_receipts_checkout: Path) -> None:
    pass


@pytest.fixture
def receipt_paths(run_receipts_checkout: Path) -> tuple[Path, Path, Path]:
    source = run_receipts_checkout / "typesafe-relevance-primary-2026-09/exported-answers.json"
    bundle = run_receipts_checkout / "typesafe-relevance-fitted-rerun-2026-09"
    return source, bundle / "fitted-oof-results.json", bundle / "checksums.json"

#: The fit runs liblinear over an OpenBLAS built DYNAMIC_ARCH, which selects a kernel
#: per CPU, so the stored probabilities only reproduce to the last couple of bits on a
#: machine other than the one that wrote them. Measured spread across kernels is 1.4e-15
#: over 185 leaves, and no count, metric or flag moves with it. Everything that is not a
#: float is still compared exactly, and test_fitted_report_checksums pins the published
#: bytes, so a byte assertion here would only buy a CPU-dependent failure.
FLOAT_TOLERANCE = 1e-9


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, str | bytes)


def _mismatches(actual: Any, expected: Any, path: str = "") -> list[str]:
    """Every leaf where a recomputed report departs from the stored one."""
    if isinstance(expected, float) and isinstance(actual, float):
        if math.isclose(actual, expected, rel_tol=FLOAT_TOLERANCE, abs_tol=FLOAT_TOLERANCE):
            return []
        return [f"{path}: {actual!r} != {expected!r}"]
    if isinstance(expected, Mapping) and isinstance(actual, Mapping):
        if actual.keys() != expected.keys():
            return [f"{path}: keys {sorted(actual)} != {sorted(expected)}"]
        return [
            mismatch
            for key in expected
            for mismatch in _mismatches(actual[key], expected[key], f"{path}.{key}")
        ]
    if _is_sequence(expected) and _is_sequence(actual):
        if len(actual) != len(expected):
            return [f"{path}: length {len(actual)} != {len(expected)}"]
        return [
            mismatch
            for index, (left, right) in enumerate(zip(actual, expected, strict=True))
            for mismatch in _mismatches(left, right, f"{path}[{index}]")
        ]
    #: Both sides are JSON-native, so the types are stable and worth insisting on:
    #: plain equality would let a bool regress to 1 in adoption_gate or human_label
    #: and still compare equal.
    if type(actual) is not type(expected):
        return [f"{path}: {type(actual).__name__} != {type(expected).__name__}"]
    if actual != expected:
        return [f"{path}: {actual!r} != {expected!r}"]
    return []


def test_fitted_report_recomputes_from_retained_answers(
    receipt_paths: tuple[Path, Path, Path],
) -> None:
    source, report, _ = receipt_paths
    source_bytes = source.read_bytes()
    actual = build_fitted_report(json.loads(source_bytes))
    actual["source_sha256"] = hashlib.sha256(source_bytes).hexdigest()
    expected = json.loads(report.read_text(encoding="utf-8"))
    assert _mismatches(actual, expected) == []


def test_fitted_rerun_is_exploratory_and_does_not_win(
    receipt_paths: tuple[Path, Path, Path],
) -> None:
    _, report_path, _ = receipt_paths
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "exploratory_retrospective"
    assert report["adoption_gate"] is False
    assert report["source_case_count"] == 79
    assert report["source_repeat_count"] == 237
    assert report["selection_rule"]["typesafe_won"] is False
    assert report["metrics"]["typesafe_fitted_oof"]["accuracy"] > report["metrics"][
        "typesafe_argmax"
    ]["accuracy"]
    assert report["metrics"]["typesafe_fitted_oof"]["accuracy"] < report["metrics"][
        "production"
    ]["accuracy"]


def test_fitted_report_checksums(receipt_paths: tuple[Path, Path, Path]) -> None:
    _, _, checksums_path = receipt_paths
    checksums = json.loads(checksums_path.read_text(encoding="utf-8"))
    for name, digest in checksums.items():
        assert hashlib.sha256((checksums_path.parent / name).read_bytes()).hexdigest() == digest
