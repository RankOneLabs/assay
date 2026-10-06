"""The promoted API reproduces the pre-move golden exactly."""

import json
import runpy
from pathlib import Path

import pytest
from assay.code_metrics import METRICS, measure, tool_versions
ROOT = Path(__file__).parents[1]
GOLDEN = ROOT / "tests/fixtures/code_metrics_golden.json"
CASES = runpy.run_path(str(ROOT / "experiments/code_metrics/tests/metric_snapshots.py"))["CASES"]


@pytest.mark.parametrize("name", CASES)
def test_promoted_measure_matches_golden(name: str) -> None:
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))[name]
    before, after, options = CASES[name]
    actual = measure(before, after, **options)
    assert tuple(actual) == METRICS
    assert tuple(expected["metrics"]) == METRICS
    for key in METRICS:
        assert actual[key] == expected["metrics"][key], (
            f"{name} {key}: expected {expected['metrics'][key]!r}, got {actual[key]!r}"
        )
    assert tool_versions() == expected["tool_versions"]
