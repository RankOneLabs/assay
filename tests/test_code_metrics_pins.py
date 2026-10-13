"""Pinned analyzer versions and snapshot cache behavior."""

import json
import socket
import tomllib
from pathlib import Path

import pytest
from code_metrics_fixtures import stub_jscpd

from assay.code_metrics import analyze, compare, pins, tools
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


def test_node_lockfile_drift_names_the_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = json.loads((pins.NODE_TOOLS / "package-lock.json").read_text())
    lock["packages"]["node_modules/typescript"]["version"] = "0.0.0"
    (tmp_path / "package-lock.json").write_text(json.dumps(lock))
    monkeypatch.setattr(pins, "NODE_TOOLS", tmp_path)
    with pytest.raises(ToolVersionMismatch) as error:
        assert_pinned_tools()
    assert error.value.tool == "typescript"
    assert error.value.resolved == "0.0.0"


def test_installed_node_metadata_drift_names_the_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "package-lock.json").write_bytes(
        (pins.NODE_TOOLS / "package-lock.json").read_bytes()
    )
    package = tmp_path / "node_modules" / "typescript"
    package.mkdir(parents=True)
    (package / "package.json").write_text('{"version":"0.0.0"}')
    monkeypatch.setattr(pins, "NODE_TOOLS", tmp_path)
    with pytest.raises(ToolVersionMismatch) as error:
        assert_pinned_tools()
    assert error.value.tool == "typescript"
    assert error.value.resolved == "0.0.0"


def test_retained_typescript_pair_recomputes_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # NODE_OPTIONS loads this before each local Node executable. Any network
    # request would fail even when a registry is reachable on the host.
    blocker = tmp_path / "deny-network.cjs"
    blocker.write_text(
        'const net = require("node:net");\n'
        'net.Socket.prototype.connect = function () { throw new Error("network disabled"); };\n'
    )
    monkeypatch.setenv("NODE_OPTIONS", f"--require={blocker}")

    def deny_python_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("network disabled")

    monkeypatch.setattr(socket.socket, "connect", deny_python_network)
    before = {
        "a.ts": 'import { b } from "./b";\nexport const a: number = b;\n',
        "b.ts": "export const b: number = 1;\n",
    }
    after = {
        "a.ts": 'import { b } from "./b";\nexport const a: number = "bad";\n',
        "b.ts": 'import { a } from "./a";\nexport const b: number = 1;\n',
    }
    tools._CACHE.clear()
    first = compare(before, after).model_dump_json()
    tools._CACHE.clear()
    second = compare(before, after).model_dump_json()
    assert first.encode() == second.encode()
    recorded = json.loads(first)
    assert recorded["before"]["typescript_metrics"] == {
        "lines": 3,
        "clones": 0,
        "duplicated_lines": 0,
        "type_errors": 0,
    }
    assert recorded["after"]["typescript_metrics"] == {
        "lines": 4,
        "clones": 0,
        "duplicated_lines": 0,
        "type_errors": 1,
    }
    assert recorded["patch"]["code_lines"] == {"before": 3, "after": 4, "delta": 1}
    assert recorded["patch"]["cyclic_scc_count"] == {"before": 0, "after": 1, "delta": 1}


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
