"""Cycle evidence from snapshot graphs and the iterative Tarjan primitive."""

import os
import subprocess
import sys
from collections.abc import Mapping

from code_metrics_fixtures import (
    FIXTURE_C_AFTER,
    FIXTURE_C_BEFORE,
    FIXTURE_D_AFTER,
    FIXTURE_D_BEFORE,
    package_snapshot,
)

from assay.code_metrics.cycles import analyze_cycles, strongly_connected_components
from assay.code_metrics.graph import build_module_graph


def _assert_side(snapshot: Mapping[str, str], cyclic: bool) -> None:
    graph, _ = build_module_graph(snapshot)
    assert tuple(item.module for item in graph.modules) == ("pkg", "pkg.a", "pkg.b", "pkg.c")
    expected_edges = [("pkg.a", "pkg.b"), ("pkg.b", "pkg.c")]
    if cyclic:
        expected_edges.append(("pkg.c", "pkg.a"))
    assert tuple((edge.importer, edge.imported) for edge in graph.edges) == tuple(expected_edges)
    report = analyze_cycles(graph)
    assert report.cyclic_component_count == int(cyclic)
    assert report.modules_in_cycles == (("pkg.a", "pkg.b", "pkg.c") if cyclic else ())
    assert tuple(item.modules for item in report.components if item.is_cyclic) == (
        (("pkg.a", "pkg.b", "pkg.c"),) if cyclic else ()
    )
    assert report.scc_count == (2 if cyclic else 4)
    assert report.cyclic_scc_count == int(cyclic)
    assert report.cyclic_module_count == (3 if cyclic else 0)
    assert report.largest_cyclic_scc_size == (3 if cyclic else 0)


def test_fixture_c_creates_cycle() -> None:
    _assert_side(FIXTURE_C_BEFORE, False)
    _assert_side(FIXTURE_C_AFTER, True)


def test_fixture_d_removes_cycle() -> None:
    _assert_side(FIXTURE_D_BEFORE, True)
    _assert_side(FIXTURE_D_AFTER, False)


def test_explicit_self_dependency() -> None:
    """Grimp cannot emit a self edge, so exercise this Tarjan branch directly."""
    components = strongly_connected_components({"pkg.a": ("pkg.a",)})
    assert [(item.modules, item.is_cyclic) for item in components] == [(("pkg.a",), True)]


def test_disjoint_cycles() -> None:
    graph, _ = build_module_graph(
        package_snapshot("pkg", {"a": ("b",), "b": ("a",), "c": ("d",), "d": ("c",)})
    )
    report = analyze_cycles(graph)
    assert report.cyclic_component_count == 2
    assert tuple(item.modules for item in report.components if item.is_cyclic) == (
        ("pkg.a", "pkg.b"),
        ("pkg.c", "pkg.d"),
    )
    assert report.modules_in_cycles == ("pkg.a", "pkg.b", "pkg.c", "pkg.d")


def test_iterative_chain_of_200() -> None:
    adjacency = {f"pkg.m{i:03}": (f"pkg.m{i + 1:03}",) if i < 199 else () for i in range(200)}
    components = strongly_connected_components(adjacency)
    assert len(components) == 200
    assert all(not item.is_cyclic for item in components)


def test_cycles_stable_across_hash_seeds() -> None:
    graph, _ = build_module_graph(FIXTURE_C_AFTER)
    expected = analyze_cycles(graph).model_dump_json()
    code = (
        "from assay.code_metrics.cycles import analyze_cycles; "
        "from assay.code_metrics.graph import build_module_graph; "
        f"print(analyze_cycles(build_module_graph({dict(FIXTURE_C_AFTER)!r})[0]).model_dump_json())"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "PYTHONHASHSEED": "73"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == expected
