"""TypeScript import graphs from pinned dependency-cruiser."""

import subprocess
from typing import Any

import pytest
from code_metrics_fixtures import stub_jscpd

from assay.code_metrics import analyze, compare, typescript
from assay.code_metrics.api import CodeMetricsConfig
from assay.code_metrics.components import ComponentConfig
from assay.code_metrics.errors import AnalyzerFailed, ToolUnavailable

APP = {
    "app/main.ts": (
        'import { a } from "./lib/a.js";\n'
        'import type { T } from "./lib/types";\n'
        'import { u } from "./util";\n'
        'import "./styles.css";\n'
        'import { readFileSync } from "node:fs";\n'
        'import { z } from "zod";\n'
        'import { Q } from "@scope/pkg/sub";\n'
        'export * from "./lib/reexport";\n'
        'export const lazy = () => import("./lib/lazy");\n'
    ),
    "app/lib/a.ts": 'import { u } from "../util/index";\nexport const a = u;\n',
    "app/lib/types.ts": "export type T = number;\n",
    "app/lib/reexport.mts": "export const re = 1;\n",
    "app/lib/lazy.tsx": "export const l = 1;\n",
    "app/util/index.ts": 'import { a } from "../lib/a";\nexport const u = 1;\n',
}


@pytest.fixture(autouse=True)
def stub_clones(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_jscpd(monkeypatch)


def test_typescript_modules_edges_and_external_dependencies() -> None:
    report = analyze(APP)
    graph = report.architecture.graph
    assert [(entry.module, entry.path, entry.language) for entry in graph.modules] == [
        (path, path, "typescript") for path in sorted(APP)
    ]
    # Type-only imports, re-exports, dynamic imports, and ".js" specifiers of
    # TypeScript sources are all edges.
    assert [(edge.importer, edge.imported) for edge in graph.edges] == [
        ("app/lib/a.ts", "app/util/index.ts"),
        ("app/main.ts", "app/lib/a.ts"),
        ("app/main.ts", "app/lib/lazy.tsx"),
        ("app/main.ts", "app/lib/reexport.mts"),
        ("app/main.ts", "app/lib/types.ts"),
        ("app/main.ts", "app/util/index.ts"),
        ("app/util/index.ts", "app/lib/a.ts"),
    ]
    assert [(item.module, item.package) for item in graph.external_dependencies] == [
        ("app/main.ts", "@scope/pkg"),
        ("app/main.ts", "app/styles.css"),
        ("app/main.ts", "fs"),
        ("app/main.ts", "zod"),
    ]
    assert report.architecture.cycles.cyclic_scc_count == 1
    assert report.architecture.cycles.largest_cyclic_scc_size == 2
    coverage = {entry.language: entry for entry in report.coverage.languages}
    assert coverage["typescript"].files_seen == coverage["typescript"].files_analyzed == 6
    assert coverage["typescript"].files_without_module == ()
    assert report.versions.tools["dependency-cruiser"] == "18.4.0"


def test_components_and_comparison_over_typescript_paths() -> None:
    config = CodeMetricsConfig(
        components=(
            ComponentConfig("entry", ("app/main.ts",)),
            ComponentConfig("lib", ("app/lib/*", "app/util/*")),
        )
    )
    after = {**APP, "app/lib/types.ts": 'import { z } from "../main";\nexport type T = number;\n'}
    result = compare(APP, after, config=config)
    added = result.structural_changes.cross_component_edges_added
    assert [(edge.importer, edge.imported) for edge in added] == [
        ("app/lib/types.ts", "app/main.ts")
    ]
    assert result.architecture_deltas.system.cross_component_edge_count.delta == 1
    assert result.new_code.new_lines is None


def test_python_only_snapshot_does_not_run_dependency_cruiser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def cruise(*args: Any) -> None:
        raise AssertionError("dependency-cruiser ran without a TypeScript file")

    monkeypatch.setattr(typescript, "_cruise", cruise)
    report = analyze({"src/pkg/__init__.py": "", "src/pkg/a.py": "x = 1\n"})
    assert report.coverage.languages[2].files_seen == 0


def test_report_conversion_keeps_snapshot_files_only() -> None:
    files = {"a.ts": "", "b.ts": "", "broken.ts": ""}
    cruise = {
        "modules": [
            {
                "source": "a.ts",
                "dependencies": [
                    {"module": "./b", "resolved": "b.ts", "coreModule": False},
                    {"module": "../up/x.json", "resolved": "../up/x.json", "coreModule": False},
                    {"module": "bun:test", "resolved": "bun:test", "coreModule": True},
                ],
            },
            {"source": "b.ts", "dependencies": []},
            {"source": "zod", "dependencies": []},
        ]
    }
    extraction = typescript._extraction(files, cruise)
    assert [entry.module for entry in extraction.graph.modules] == ["a.ts", "b.ts"]
    assert [item.package for item in extraction.graph.external_dependencies] == [
        "../up/x.json",
        "bun:test",
    ]
    assert extraction.coverage.files_without_module == ("broken.ts",)
    with pytest.raises(AnalyzerFailed, match="report unreadable"):
        typescript._extraction(files, {"modules": [{"source": "a.ts"}]})


def _fake_npx(
    monkeypatch: pytest.MonkeyPatch, version: int, cruise: subprocess.CompletedProcess[str]
) -> None:
    original_run = subprocess.run

    def run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        command = args[0]
        if isinstance(command, list) and "depcruise" in command:
            if "--version" in command:
                if version:
                    raise subprocess.CalledProcessError(version, command, stderr="fetch failed")
                return subprocess.CompletedProcess(command, 0, "18.4.0\n", "")
            return cruise
        return original_run(*args, **kwargs)  # type: ignore[no-any-return]

    monkeypatch.setattr(typescript.subprocess, "run", run)


def test_dependency_cruiser_failures_are_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = {"a.ts": "export {};\n"}
    _fake_npx(monkeypatch, 1, subprocess.CompletedProcess([], 0, "", ""))
    with pytest.raises(ToolUnavailable, match=r"dependency-cruiser@18\.4\.0: fetch failed"):
        analyze(snapshot)
    _fake_npx(monkeypatch, 0, subprocess.CompletedProcess([], 1, "", "parse crashed"))
    with pytest.raises(AnalyzerFailed, match="dependency-cruiser failed: parse crashed"):
        analyze(snapshot)
    _fake_npx(monkeypatch, 0, subprocess.CompletedProcess([], 0, "not json", ""))
    with pytest.raises(AnalyzerFailed, match="report unreadable"):
        analyze(snapshot)
