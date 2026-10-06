"""Golden output captured from the original experiments implementation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from code_metrics import METRICS, measure, tool_versions
from metric_snapshots import BEFORE, DELEGATING, INLINED, _after

GOLDEN = Path(__file__).resolve().parents[3] / "tests/fixtures/code_metrics_golden.json"
CASES = {
    "unchanged": (BEFORE, dict(BEFORE), {}),
    "delegating": (BEFORE, _after(DELEGATING), {}),
    "inlined": (
        BEFORE,
        _after(INLINED, "from shop.store import audit, load\n"),
        {"clone_min_lines": 3, "clone_min_tokens": 15},
    ),
    "first_python_file": ({}, {"module.py": "x = 1\n"}, {}),
    "last_python_file": ({"module.py": "x = 1\n"}, {"README.md": ""}, {}),
    "single_module": (
        {"module.py": "x = 1\n"},
        {"module.py": "import os\nx = 1\n"},
        {},
    ),
}


def record() -> None:
    """Regenerate with: cd experiments && uv run python code_metrics/tests/test_code_metrics_golden.py"""
    data = {
        name: {"metrics": measure(before, after, **options), "tool_versions": tool_versions()}
        for name, (before, after, options) in CASES.items()
    }
    GOLDEN.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


@pytest.mark.parametrize("name", CASES)
def test_golden(name: str) -> None:
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


if __name__ == "__main__":
    record()
