"""Component assignment, coupling, and cohesion from extracted graphs."""

import pytest
from code_metrics_fixtures import FIXTURE_COUPLING, FIXTURE_I, FIXTURE_J

from assay.code_metrics.components import ComponentConfig, analyze_components, assign_components
from assay.code_metrics.errors import (
    AmbiguousComponentConfig,
    ConfigurationError,
    EmptyComponentPattern,
)
from assay.code_metrics.graph import build_module_graph


def _config() -> tuple[ComponentConfig, ...]:
    return (
        ComponentConfig("alpha", ("src/pkg/a.py", "src/pkg/b.py")),
        ComponentConfig("beta", ("src/pkg/c.py", "src/pkg/d.py")),
    )


def test_fixture_i_ambiguous_assignment() -> None:
    graph, _ = build_module_graph(FIXTURE_I)
    with pytest.raises(AmbiguousComponentConfig) as caught:
        assign_components(
            graph,
            (
                ComponentConfig("alpha", ("src/pkg/a.py",)),
                ComponentConfig("beta", ("src/pkg/*.py",)),
            ),
        )
    assert all(value in str(caught.value) for value in ("pkg.a", "alpha", "beta"))


def test_fixture_j_unassigned_is_reported_with_metrics() -> None:
    graph, _ = build_module_graph(FIXTURE_J)
    report = analyze_components(graph, (ComponentConfig("alpha", ("src/pkg/a.py",)),))
    assert [(item.module, item.path, item.component) for item in report.module_components] == [
        ("pkg", "src/pkg/__init__.py", "unassigned"),
        ("pkg.a", "src/pkg/a.py", "alpha"),
        ("pkg.b", "src/pkg/b.py", "unassigned"),
    ]
    unassigned = next(item for item in report.component_coupling if item.component == "unassigned")
    assert (unassigned.afferent, unassigned.efferent, unassigned.instability) == (1, 0, 0.0)
    assert (unassigned.module_count, unassigned.internal_edges) == (2, 0)
    assert unassigned.relational_cohesion == 0.5
    assert unassigned.internal_dependency_density == 0.0
    assert unassigned.internal_edge_share == 0.0


def test_configuration_errors() -> None:
    graph, _ = build_module_graph(FIXTURE_I)
    with pytest.raises(EmptyComponentPattern, match=r"missing\.py"):
        assign_components(graph, (ComponentConfig("alpha", ("src/pkg/missing.py",)),))
    with pytest.raises(ConfigurationError, match="unassigned"):
        assign_components(graph, (ComponentConfig("unassigned", ("src/pkg/a.py",)),))


def test_exact_coupling_and_cohesion_fixture() -> None:
    graph, _ = build_module_graph(FIXTURE_COUPLING)
    assert tuple(item.module for item in graph.modules) == (
        "pkg",
        "pkg.a",
        "pkg.b",
        "pkg.c",
        "pkg.d",
    )
    assert tuple((edge.importer, edge.imported) for edge in graph.edges) == (
        ("pkg.a", "pkg.b"),
        ("pkg.b", "pkg.c"),
        ("pkg.d", "pkg.a"),
    )
    report = analyze_components(graph, _config())
    by_name = {item.component: item for item in report.component_coupling}
    for name in ("alpha", "beta"):
        item = by_name[name]
        assert (item.afferent, item.efferent, item.instability) == (1, 1, 0.5)
        assert item.module_count == 2
    alpha, beta = by_name["alpha"], by_name["beta"]
    assert (alpha.internal_edges, alpha.incoming_edges, alpha.outgoing_edges) == (1, 1, 1)
    assert (alpha.relational_cohesion, alpha.internal_dependency_density) == (1.0, 0.5)
    assert alpha.internal_edge_share == pytest.approx(1 / 3)
    assert (beta.internal_edges, beta.incoming_edges, beta.outgoing_edges) == (0, 1, 1)
    assert (
        beta.relational_cohesion,
        beta.internal_dependency_density,
        beta.internal_edge_share,
    ) == (0.5, 0.0, 0.0)
    assert tuple(
        (pair.importer_component, pair.imported_component, pair.edge_count)
        for pair in report.boundaries
    ) == (("alpha", "beta", 1), ("beta", "alpha", 1))
    assert [(item.module, item.fan_in, item.fan_out) for item in report.module_coupling] == [
        ("pkg", 0, 0),
        ("pkg.a", 1, 1),
        ("pkg.b", 1, 1),
        ("pkg.c", 1, 0),
        ("pkg.d", 0, 1),
    ]


def test_zero_denominators() -> None:
    graph, _ = build_module_graph(FIXTURE_I)
    report = analyze_components(graph, (ComponentConfig("alpha", ("src/pkg/a.py",)),))
    alpha = next(item for item in report.component_coupling if item.component == "alpha")
    assert alpha.internal_dependency_density is None
    assert alpha.instability is None
    assert alpha.internal_edge_share is None
