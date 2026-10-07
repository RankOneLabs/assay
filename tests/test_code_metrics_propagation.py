"""Transitive visibility over graph-builder evidence."""

import pytest
from code_metrics_fixtures import FIXTURE_A, FIXTURE_B_AFTER, FIXTURE_B_BEFORE, FIXTURE_H

from assay.code_metrics.graph import build_module_graph
from assay.code_metrics.models import ImportEdge, ModuleEntry, ModuleGraph
from assay.code_metrics.propagation import analyze_propagation


def test_package_chain_arithmetic() -> None:
    graph, _ = build_module_graph(FIXTURE_A)
    assert tuple(entry.module for entry in graph.modules) == ("pkg", "pkg.a", "pkg.b", "pkg.c")
    assert tuple((edge.importer, edge.imported) for edge in graph.edges) == (
        ("pkg.a", "pkg.b"),
        ("pkg.b", "pkg.c"),
    )
    # The package initializer is a fourth isolated module. Take the chain's
    # induced graph to assert its requested three-node arithmetic exactly.
    chain = ModuleGraph(modules=graph.modules[1:], edges=graph.edges, external_dependencies=())
    report = analyze_propagation(chain)
    assert [(item.module, item.reaches, item.reached_by) for item in report.module_visibility] == [
        ("pkg.a", 3, 1),
        ("pkg.b", 2, 2),
        ("pkg.c", 1, 3),
    ]
    assert sum(item.reaches for item in report.module_visibility) == 6
    assert len(report.module_visibility) ** 2 == 9
    assert report.propagation_cost == pytest.approx(6 / 9)
    full = analyze_propagation(graph)
    assert full.module_visibility[0].reaches == 1
    assert full.propagation_cost == pytest.approx(7 / 16)


def test_empty_and_single_module() -> None:
    empty, _ = build_module_graph({"solo.py": "pass\n"})
    assert analyze_propagation(empty).propagation_cost is None
    graph, _ = build_module_graph(FIXTURE_H)
    single = ModuleGraph(modules=(graph.modules[1],), edges=(), external_dependencies=())
    report = analyze_propagation(single)
    assert report.propagation_cost == 1.0
    assert [(item.reaches, item.reached_by) for item in report.module_visibility] == [(1, 1)]


def test_iterative_chain_of_200() -> None:
    names = tuple(f"pkg.m{i:03}" for i in range(200))
    graph = ModuleGraph(
        modules=tuple(ModuleEntry(module=name, path=None) for name in names),
        edges=tuple(
            ImportEdge(importer=names[index], imported=names[index + 1])
            for index in range(len(names) - 1)
        ),
        external_dependencies=(),
    )
    report = analyze_propagation(graph)
    assert report.module_visibility[0].reaches == 200
    assert report.module_visibility[-1].reaches == 1
    assert report.module_visibility[0].reached_by == 1
    assert report.module_visibility[-1].reached_by == 200
    assert report.propagation_cost == pytest.approx(sum(range(1, 201)) / 200**2)


def test_fixture_b_propagation_cost_rises_with_the_added_edge() -> None:
    before, _ = build_module_graph(FIXTURE_B_BEFORE)
    after, _ = build_module_graph(FIXTURE_B_AFTER)
    for graph in (before, after):
        assert tuple(entry.module for entry in graph.modules) == (
            "pkg",
            "pkg.a",
            "pkg.b",
            "pkg.c",
        )
    assert tuple((edge.importer, edge.imported) for edge in before.edges) == (("pkg.a", "pkg.b"),)
    assert tuple((edge.importer, edge.imported) for edge in after.edges) == (
        ("pkg.a", "pkg.b"),
        ("pkg.a", "pkg.c"),
    )
    assert analyze_propagation(before).propagation_cost == pytest.approx(5 / 16)
    assert analyze_propagation(after).propagation_cost == pytest.approx(6 / 16)
    # The package initializer is a fourth isolated module. Take the induced
    # three-module graph to assert the fixture's requested arithmetic exactly.
    before_induced = ModuleGraph(
        modules=before.modules[1:], edges=before.edges, external_dependencies=()
    )
    after_induced = ModuleGraph(
        modules=after.modules[1:], edges=after.edges, external_dependencies=()
    )
    assert analyze_propagation(before_induced).propagation_cost == pytest.approx(4 / 9)
    assert analyze_propagation(after_induced).propagation_cost == pytest.approx(5 / 9)
