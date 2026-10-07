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
])
def test_invalid_snapshot_is_rejected_before_materialization(snapshot, monkeypatch) -> None:
    from assay.code_metrics import graph as extractor

    def materialize():
        pytest.fail("invalid snapshot reached filesystem materialization")

    monkeypatch.setattr(extractor.tempfile, "TemporaryDirectory", materialize)
    with pytest.raises(ValueError):
        build_module_graph(snapshot)


def test_snapshot_beyond_study_repository_caps_is_accepted() -> None:
    snapshot = {f"pkg/m{i}.py": "" for i in range(250)} | {
        "pkg/__init__.py": "",
        "pkg/big.py": "x = 1\n" * 200_000,
    }
    graph, coverage = build_module_graph(snapshot)
    assert len(graph.modules) == 252
    assert coverage.python_files_seen == 252


def test_package_named_like_an_imported_module_graphs_the_snapshot() -> None:
    # assay and pydantic are already imported here; the snapshot must still win.
    for package in ("assay", "pydantic"):
        assert package in sys.modules
        graph, coverage = build_module_graph(
            package_snapshot(package, {"a": ("b",), "b": ()})
        )
        assert _nodes(graph) == (package, f"{package}.a", f"{package}.b")
        assert _edges(graph) == ((f"{package}.a", f"{package}.b"),)
        assert coverage.files_without_module == ()


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


def test_unicode_module_names_are_graphed() -> None:
    snapshot = {"pkg/__init__.py": "", "pkg/café.py": "import pkg\n"}
    graph, coverage = build_module_graph(snapshot)
    assert _nodes(graph) == ("pkg", "pkg.café")
    assert _edges(graph) == (("pkg.café", "pkg"),)
    assert coverage.files_without_module == ()


def test_non_identifier_names_stay_outside_the_graph() -> None:
    snapshot = {
        "my-pkg/__init__.py": "import json\n",
        "pkg/__init__.py": "",
        "pkg/my-mod.py": "import pkg\n",
    }
    graph, coverage = build_module_graph(snapshot)
    assert _nodes(graph) == ("pkg",)
    assert _edges(graph) == ()
    assert coverage.files_without_module == ("my-pkg/__init__.py", "pkg/my-mod.py")


def test_relative_import_above_top_level_package_is_dropped() -> None:
    snapshot = {"pkg/__init__.py": "from .. import nothing\nimport json\n"}
    graph, _ = build_module_graph(snapshot)
    assert _nodes(graph) == ("pkg",)
    assert [(item.module, item.package) for item in graph.external_dependencies] == [
        ("pkg", "json")
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
