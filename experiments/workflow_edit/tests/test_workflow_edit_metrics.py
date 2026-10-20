"""The metric step on real oakridge trees: the fixture's toolchain, true edges, exact
offline recomputation of the retained smoke-edit before/after pair."""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
import socket
from pathlib import Path

import pytest

from assay.code_metrics import CodeMetricsConfig, analyze, tools
from assay.code_metrics.cli_snapshot import snapshot_directory
from assay.code_metrics.errors import ToolUnavailable
from workflow_edit.fixture import SMOKE_EDIT, load_fixture, materialize
from workflow_edit.metrics import (
    LOCK,
    TYPESCRIPT,
    install_toolchain,
    measure_pair,
    measure_patch,
    metrics_config,
)

_SPECIFIER = re.compile(
    r"^\s*(?:import|export)\b[^;]*?[\s}]from\s*\"([^\"]+)\"|^\s*import\s*\"([^\"]+)\"",
    re.MULTILINE | re.DOTALL,
)
# Formed by type-only imports alone, at the pin and after the reference.
CYCLE = [
    "src/domain/compiled-workflow.ts",
    "src/domain/delegated-session.ts",
    "src/domain/workflow.ts",
]


@pytest.fixture(scope="module")
def dependencies(tmp_path_factory: pytest.TempPathFactory) -> Path:
    target = tmp_path_factory.mktemp("typescript-dependencies")
    try:
        return install_toolchain(target, offline=True)
    except ToolUnavailable:
        # A cold npm cache: installing, unlike measuring, may fetch.
        return install_toolchain(target)


@pytest.fixture
def no_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # As tests/test_code_metrics_pins.py: every local Node executable loads the
    # blocker, and Python sockets refuse to connect, even with a registry reachable.
    blocker = tmp_path / "deny-network.cjs"
    blocker.write_text(
        'const net = require("node:net");\n'
        'net.Socket.prototype.connect = function () { throw new Error("network disabled"); };\n'
    )
    monkeypatch.setenv("NODE_OPTIONS", f"--require={blocker}")

    def deny(*args: object, **kwargs: object) -> None:
        raise AssertionError("network disabled")

    monkeypatch.setattr(socket.socket, "connect", deny)


def _edges(graph: dict) -> set[tuple[str, str]]:
    return {(edge["importer"], edge["imported"]) for edge in graph["edges"]}


def test_retained_reference_pair_recomputes_exactly_offline(
    dependencies: Path, no_network: None
) -> None:
    fixture = load_fixture()
    tools._CACHE.clear()
    first = measure_patch(fixture, fixture.reference_patch, dependencies=dependencies)
    tools._CACHE.clear()
    second = measure_patch(fixture, fixture.reference_patch, dependencies=dependencies)
    assert first.model_dump_json().encode() == second.model_dump_json().encode()

    recorded = json.loads(first.model_dump_json())
    lock = hashlib.sha256((LOCK / "package-lock.json").read_bytes()).hexdigest()
    for side, lines in (("before", 5545), ("after", 5571)):
        report = recorded[side]
        # The reference passes the fixture's own typecheck, so zero is the true count.
        assert report["typescript_metrics"]["type_errors"] == 0
        assert report["typescript_metrics"]["lines"] == lines
        assert report["versions"]["tools"]["typecheck-typescript"] == TYPESCRIPT
        assert report["versions"]["tools"]["typecheck-lock"] == f"sha256:{lock}"
        (coverage,) = (
            item for item in report["coverage"]["languages"] if item["language"] == "typescript"
        )
        assert coverage["files_seen"] == coverage["modules_discovered"] == 52
        assert coverage["files_without_module"] == []
        assert report["architecture"]["cycles"]["modules_in_cycles"] == CYCLE
    assert len(recorded["before"]["architecture"]["graph"]["edges"]) == 147
    assert len(recorded["after"]["architecture"]["graph"]["edges"]) == 148
    assert recorded["structural_changes"]["edges_added"] == [
        {"importer": "src/validation/slot-binding.ts", "imported": "src/domain/json-pointer.ts"}
    ]
    assert recorded["structural_changes"]["edges_removed"] == []
    assert recorded["patch"]["new_cycles"] == []
    assert recorded["patch"]["cyclic_scc_count"] == {"before": 1, "after": 1, "delta": 0}
    assert recorded["patch"]["added_lines"] == 29
    assert recorded["patch"]["removed_lines"] == 5
    assert recorded["patch"]["changed_modules"] == [
        "src/compiler/context-requirements.ts",
        "src/compiler/resolve-execution.ts",
        "src/domain/delegated-session.ts",
        "src/domain/json-pointer.ts",
        "src/validation/slot-binding.ts",
    ]


def test_empty_patch_measures_an_unchanged_tree(dependencies: Path) -> None:
    comparison = measure_patch(load_fixture(), "", dependencies=dependencies)
    assert comparison.before == comparison.after


def test_real_tree_graph_matches_its_import_statements(dependencies: Path) -> None:
    snapshot, _ = snapshot_directory(SMOKE_EDIT / "repository")
    graph = json.loads(analyze(snapshot, config=metrics_config(dependencies)).model_dump_json())[
        "architecture"
    ]["graph"]
    expected: set[tuple[str, str]] = set()
    packages: set[str] = set()
    for path, source in snapshot.items():
        for match in _SPECIFIER.finditer(source):
            specifier = match.group(1) or match.group(2)
            if not specifier.startswith("."):
                packages.add(specifier)
                continue
            # Extensionless ESM, as bun and the bundler resolution resolve it.
            target = posixpath.normpath(posixpath.join(posixpath.dirname(path), specifier))
            resolved = [c for c in (target, f"{target}.ts", f"{target}/index.ts") if c in snapshot]
            assert resolved, (path, specifier)
            expected.add((path, resolved[0]))
    assert _edges(graph) == expected
    assert packages == {"bun:test", "node:crypto", "zod"}
    # Every relative import resolved; only packages are external (node: is dropped).
    assert {item["package"] for item in graph["external_dependencies"]} == {
        "bun:test", "crypto", "zod"
    }
    # projects.ts imports only types; the edge still couples it at compile time.
    assert ("src/domain/projects.ts", "src/domain/primitives.ts") in _edges(graph)
    assert "import type" in snapshot["src/domain/projects.ts"]


def test_new_type_only_cycle_and_tree_compiler_options_are_seen(
    dependencies: Path, tmp_path: Path
) -> None:
    fixture = load_fixture()
    before, after = tmp_path / "before", tmp_path / "after"
    materialize(before, fixture.repository, fixture.reference_patch)
    materialize(after, fixture.repository, fixture.reference_patch)
    pointer = after / "src/domain/json-pointer.ts"
    pointer.write_text(
        'import type { bindableSchema } from "../validation/slot-binding";\n'
        + pointer.read_text()
        + "export type Bindable = typeof bindableSchema;\n"
    )
    measured = measure_pair(before, after, dependencies=dependencies)
    comparison = json.loads(measured.model_dump_json())
    assert comparison["patch"]["new_cycles"] == [
        ["src/domain/json-pointer.ts", "src/validation/slot-binding.ts"]
    ]
    assert comparison["after"]["typescript_metrics"]["type_errors"] == 0

    # noUnusedLocals comes from the tree's tsconfig; the synthetic project lacks it.
    unused = fixture.repository | {
        "src/domain/projects.ts": fixture.repository["src/domain/projects.ts"]
        + "const unused = 1;\n"
    }
    snapshot = {
        path: text
        for path, text in unused.items()
        if path.endswith(".ts") or path == "tsconfig.json"
    }
    config = metrics_config(dependencies)
    assert analyze(snapshot, config=config).typescript_metrics.type_errors == 1
    clean = {path: fixture.repository[path] for path in snapshot}
    assert (
        analyze(snapshot, config=CodeMetricsConfig()).typescript_metrics.type_errors
        == analyze(clean, config=CodeMetricsConfig()).typescript_metrics.type_errors
    )
