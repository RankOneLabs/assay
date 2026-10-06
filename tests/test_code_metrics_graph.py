"""First-party graph evidence is complete, sorted, and stable."""

import os
import subprocess
import sys

import pytest
from code_metrics_fixtures import FIXTURE_A, FIXTURE_H, package_snapshot

from assay.code_metrics.graph import build_module_graph


@pytest.mark.parametrize("snapshot", [
    {"pkg/a.py": "", "pkg//a.py": ""},
    {"pkg/./a.py": ""},
    {"pkg/a.py": "", "pkg/a.py/b.py": ""},
    {"pkg/A.py": "", "pkg/a.py": ""},
    {"../notes.txt": "", "pkg/__init__.py": ""},
    {f"file{i}.txt": "" for i in range(201)},
    {"notes.txt": "x" * 1_000_001},
])
def test_invalid_snapshot_is_rejected_before_materialization(snapshot, monkeypatch) -> None:
    from assay.code_metrics import graph as extractor

    def materialize():
        pytest.fail("invalid snapshot reached filesystem materialization")

    monkeypatch.setattr(extractor.tempfile, "TemporaryDirectory", materialize)
    with pytest.raises(ValueError):
        build_module_graph(snapshot)


def _nodes(graph: object) -> tuple[str, ...]:
    return tuple(entry.module for entry in graph.modules)  # type: ignore[attr-defined]


def _edges(graph: object) -> tuple[tuple[str, str], ...]:
    return tuple((edge.importer, edge.imported) for edge in graph.edges)  # type: ignore[attr-defined]


def test_fixture_a_chain() -> None:
    """Fixture A uses package prefix pkg."""
    graph, coverage = build_module_graph(FIXTURE_A)
    assert _nodes(graph) == ("pkg", "pkg.a", "pkg.b", "pkg.c")
    assert _edges(graph) == (("pkg.a", "pkg.b"), ("pkg.b", "pkg.c"))
    assert graph.modules[0].path == "src/pkg/__init__.py"
    assert coverage.modules_discovered == 4
    assert coverage.files_without_module == ()


def test_fixture_h_isolated() -> None:
    """Fixture H uses package prefix pkg."""
    graph, _ = build_module_graph(FIXTURE_H)
    assert _nodes(graph) == ("pkg", "pkg.isolated")
    assert _edges(graph) == ()
    isolated = graph.modules[1].module
    fan_in = sum(edge.imported == isolated for edge in graph.edges)
    fan_out = sum(edge.importer == isolated for edge in graph.edges)
    assert (fan_in, fan_out) == (0, 0)


def test_no_package_and_unmapped_python_file() -> None:
    graph, coverage = build_module_graph({"solo.py": "pass\n"})
    assert _nodes(graph) == ()
    assert _edges(graph) == ()
    assert coverage.files_without_module == ("solo.py",)
    assert coverage.python_files_seen == 1
    graph, coverage = build_module_graph({**FIXTURE_H, "loose.py": "pass\n"})
    assert _nodes(graph) == ("pkg", "pkg.isolated")
    assert _edges(graph) == ()
    assert coverage.files_without_module == ("loose.py",)
    assert coverage.python_files_seen > coverage.modules_discovered


def test_external_dependency_is_evidence_only() -> None:
    snapshot = {**package_snapshot("pkg", {"a": ()}), "src/pkg/a.py": "import json\n"}
    graph, _ = build_module_graph(snapshot)
    assert _nodes(graph) == ("pkg", "pkg.a")
    assert _edges(graph) == ()
    assert [(item.module, item.package) for item in graph.external_dependencies] == [
        ("pkg.a", "json")
    ]


def test_namespace_module_has_no_synthetic_path(monkeypatch) -> None:
    from assay.code_metrics import graph as extractor

    class FakeGraph:
        modules = {"pkg", "pkg.namespace"}

        def find_modules_directly_imported_by(self, module: str) -> set[str]:
            return set()

    monkeypatch.setattr(extractor.grimp, "build_graph", lambda *args, **kwargs: FakeGraph())
    graph, coverage = build_module_graph({"src/pkg/__init__.py": ""})
    assert _nodes(graph) == ("pkg", "pkg.namespace")
    assert _edges(graph) == ()
    assert graph.modules[0].path == "src/pkg/__init__.py"
    assert graph.modules[1].path is None
    assert coverage.files_without_module == ()


def test_graph_is_stable_across_hash_seeds() -> None:
    graph, _ = build_module_graph(FIXTURE_A)
    assert graph.model_dump_json() == build_module_graph(FIXTURE_A)[0].model_dump_json()
    code = (
        "from assay.code_metrics.graph import build_module_graph; "
        f"print(build_module_graph({dict(FIXTURE_A)!r})[0].model_dump_json())"
    )
    env = {**os.environ, "PYTHONHASHSEED": "73"}
    result = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == graph.model_dump_json()
