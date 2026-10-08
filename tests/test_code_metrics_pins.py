"""Pinned analyzer versions and snapshot cache behavior."""

import tomllib
from pathlib import Path

import pytest
from code_metrics_fixtures import stub_jscpd

from assay.code_metrics import analyze, tools
from assay.code_metrics.errors import ToolVersionMismatch
from assay.code_metrics.models import _Config
from assay.code_metrics.pins import PINS, RUST_PINS, assert_pinned_tools


def test_pins_match_declared_extra() -> None:
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    extra = project["project"]["optional-dependencies"]["code-metrics"]
    assert {name: pin for name, pin in (item.split("==") for item in extra)} == PINS | RUST_PINS


def test_version_mismatch_names_all_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("assay.code_metrics.pins.version", lambda name: "0.0.0")
    with pytest.raises(ToolVersionMismatch) as error:
        assert_pinned_tools()
    assert error.value.tool == "radon"
    assert error.value.expected == PINS["radon"]
    assert error.value.resolved == "0.0.0"
    assert all(value in str(error.value) for value in ("radon", PINS["radon"], "0.0.0"))


def test_snapshot_cache_is_bounded_and_empty_results_are_fresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _Config(5, 50, ())
    first, second = tools._snapshot({}, config), tools._snapshot({"README.md": ""}, config)
    assert first is not second
    first["mi"]["injected"] = 1
    assert second["mi"] == {}

    monkeypatch.setattr(
        tools, "code_complexity", lambda text: type("Result", (), {"complexity": 0})()
    )
    monkeypatch.setattr(
        tools, "_ruff", lambda root, ignore: {"ruff.violations": 0, "ruff.magic_values": 0}
    )
    monkeypatch.setattr(tools, "_mypy", lambda root: 0)
    stub_jscpd(monkeypatch)
    monkeypatch.setattr(tools, "_functions", lambda root: [])
    tools._CACHE.clear()
    try:
        for number in range(9):
            report = analyze({"module.py": f"x = {number}\n"})
            assert report.existing_metrics.radon_sloc == 1
        assert len(tools._CACHE) == 8
    finally:
        tools._CACHE.clear()
