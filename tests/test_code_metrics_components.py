"""Component assignment, coupling, and cohesion from extracted graphs."""

import os
import subprocess
import sys
from typing import NamedTuple

import pytest
from code_metrics_fixtures import (
    FIXTURE_B_AFTER,
    FIXTURE_B_BEFORE,
    FIXTURE_COUPLING,
    FIXTURE_E_AFTER,
    FIXTURE_E_BEFORE,
    FIXTURE_F_AFTER,
    FIXTURE_F_BEFORE,
    FIXTURE_G_AFTER,
    FIXTURE_G_BEFORE,
    FIXTURE_I,
    FIXTURE_J,
)

from assay.code_metrics.components import (
    ComponentConfig,
    analyze_components,
    assign_components,
    collect_unmatched_patterns,
)
from assay.code_metrics.errors import (
    AmbiguousComponentConfig,
    ConfigurationError,
    EmptyComponentPattern,
)
from assay.code_metrics.graph import build_module_graph
from assay.code_metrics.models import ComponentCoupling, ComponentMetricsReport, Snapshot


def _config() -> tuple[ComponentConfig, ...]:
    return (
        ComponentConfig("alpha", ("src/pkg/a.py", "src/pkg/b.py")),
        ComponentConfig("beta", ("src/pkg/c.py", "src/pkg/d.py")),
    )


class _Side(NamedTuple):
    """One snapshot's graph evidence beside its component metrics."""

    modules: tuple[str, ...]
    edges: tuple[tuple[str, str], ...]
    report: ComponentMetricsReport


def _side(snapshot: Snapshot, configuration: tuple[ComponentConfig, ...]) -> _Side:
    """Extract the graph once, so evidence and metrics describe the same run."""
    graph, _ = build_module_graph(snapshot)
    return _Side(
        modules=tuple(item.module for item in graph.modules),
        edges=tuple((edge.importer, edge.imported) for edge in graph.edges),
        report=analyze_components(graph, configuration),
    )


def _component(report: ComponentMetricsReport, name: str) -> ComponentCoupling:
    return next(item for item in report.component_coupling if item.component == name)


def _boundaries(report: ComponentMetricsReport) -> tuple[tuple[str, str, int], ...]:
    return tuple(
        (pair.importer_component, pair.imported_component, pair.edge_count)
        for pair in report.boundaries
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
    unassigned = _component(report, "unassigned")
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


def test_collects_every_unmatched_pair_in_configuration_order() -> None:
    graph, _ = build_module_graph(FIXTURE_I)
    configuration = (
        ComponentConfig("alpha", ("missing/*", "src/pkg/a.py", "absent/*")),
        ComponentConfig("beta", ("missing/*",)),
    )
    assert collect_unmatched_patterns((graph,), configuration) == (
        ("alpha", "missing/*"),
        ("alpha", "absent/*"),
        ("beta", "missing/*"),
    )
    with pytest.raises(
        EmptyComponentPattern,
        match=r"configure components: component alpha pattern 'missing/\*' matched zero modules",
    ):
        assign_components(graph, configuration)


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
    assert _boundaries(report) == (("alpha", "beta", 1), ("beta", "alpha", 1))
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
    alpha = _component(report, "alpha")
    assert alpha.internal_dependency_density is None
    assert alpha.instability is None
    assert alpha.internal_edge_share is None


def test_namespace_module_matches_dotted_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    from assay.code_metrics import graph as extractor

    class FakeGraph:
        modules = {"pkg", "pkg.namespace"}

        def find_modules_directly_imported_by(self, module: str) -> set[str]:
            return set()

    monkeypatch.setattr(extractor.grimp, "build_graph", lambda *args, **kwargs: FakeGraph())
    graph, _ = build_module_graph({"src/pkg/__init__.py": ""})
    result = assign_components(graph, (ComponentConfig("namespace", ("pkg.namespace",)),))
    assert [(entry.module, entry.path, entry.component) for entry in result] == [
        ("pkg", "src/pkg/__init__.py", "unassigned"),
        ("pkg.namespace", None, "namespace"),
    ]


def test_component_output_stable_across_hash_seeds() -> None:
    graph, _ = build_module_graph(FIXTURE_COUPLING)
    expected = analyze_components(graph, _config()).model_dump_json()
    code = (
        "from assay.code_metrics.components import ComponentConfig, analyze_components; "
        "from assay.code_metrics.graph import build_module_graph; "
        f"graph = build_module_graph({dict(FIXTURE_COUPLING)!r})[0]; "
        "config = (ComponentConfig('alpha', ('src/pkg/a.py', 'src/pkg/b.py')), "
        "ComponentConfig('beta', ('src/pkg/c.py', 'src/pkg/d.py'))); "
        "print(analyze_components(graph, config).model_dump_json())"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "PYTHONHASHSEED": "73"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == expected


def test_fixture_b_added_direct_dependency() -> None:
    """Fixture B: one new edge out of pkg.a, and alpha's Ce moves with it."""
    configuration = (
        ComponentConfig("alpha", ("src/pkg/a.py", "src/pkg/b.py")),
        ComponentConfig("beta", ("src/pkg/c.py",)),
    )
    before = _side(FIXTURE_B_BEFORE, configuration)
    after = _side(FIXTURE_B_AFTER, configuration)
    assert before.modules == ("pkg", "pkg.a", "pkg.b", "pkg.c")
    assert after.modules == before.modules
    assert before.edges == (("pkg.a", "pkg.b"),)
    assert after.edges == (("pkg.a", "pkg.b"), ("pkg.a", "pkg.c"))
    assert len(after.edges) - len(before.edges) == 1
    before_fan_out = {item.module: item.fan_out for item in before.report.module_coupling}
    after_fan_out = {item.module: item.fan_out for item in after.report.module_coupling}
    assert (before_fan_out["pkg.a"], after_fan_out["pkg.a"]) == (1, 2)
    before_alpha = _component(before.report, "alpha")
    after_alpha = _component(after.report, "alpha")
    assert (before_alpha.efferent, before_alpha.instability) == (0, None)
    assert (after_alpha.efferent, after_alpha.instability) == (1, 1.0)
    assert (after_alpha.internal_edges, after_alpha.outgoing_edges) == (1, 1)
    after_beta = _component(after.report, "beta")
    assert (after_beta.afferent, after_beta.instability) == (1, 0.0)
    assert _boundaries(before.report) == ()
    assert _boundaries(after.report) == (("alpha", "beta", 1),)


def test_fixture_e_cross_boundary_dependency() -> None:
    """Fixture E: pkg.b -> pkg.c is the only alpha-to-beta edge."""
    configuration = _config()
    before = _side(FIXTURE_E_BEFORE, configuration)
    after = _side(FIXTURE_E_AFTER, configuration)
    assert before.modules == ("pkg", "pkg.a", "pkg.b", "pkg.c", "pkg.d")
    assert after.modules == before.modules
    assert before.edges == (("pkg.a", "pkg.b"), ("pkg.c", "pkg.d"))
    assert after.edges == (("pkg.a", "pkg.b"), ("pkg.b", "pkg.c"), ("pkg.c", "pkg.d"))
    for name in ("alpha", "beta"):
        item = _component(before.report, name)
        assert (item.afferent, item.efferent, item.instability) == (0, 0, None)
        assert (item.internal_edges, item.incoming_edges, item.outgoing_edges) == (1, 0, 0)
    alpha = _component(after.report, "alpha")
    beta = _component(after.report, "beta")
    assert (alpha.afferent, alpha.efferent, alpha.instability) == (0, 1, 1.0)
    assert (alpha.internal_edges, alpha.incoming_edges, alpha.outgoing_edges) == (1, 0, 1)
    assert (beta.afferent, beta.efferent, beta.instability) == (1, 0, 0.0)
    assert (beta.internal_edges, beta.incoming_edges, beta.outgoing_edges) == (1, 1, 0)
    assert _boundaries(before.report) == ()
    assert _boundaries(after.report) == (("alpha", "beta", 1),)


def test_fixture_f_cohesion_increase() -> None:
    """Fixture F: alpha gains two internal edges at a fixed module count."""
    configuration = (ComponentConfig("alpha", ("src/pkg/a.py", "src/pkg/b.py", "src/pkg/c.py")),)
    before = _side(FIXTURE_F_BEFORE, configuration)
    after = _side(FIXTURE_F_AFTER, configuration)
    assert before.modules == ("pkg", "pkg.a", "pkg.b", "pkg.c")
    assert after.modules == before.modules
    assert before.edges == (("pkg.a", "pkg.b"),)
    assert after.edges == (("pkg.a", "pkg.b"), ("pkg.b", "pkg.c"), ("pkg.c", "pkg.a"))
    before_alpha = _component(before.report, "alpha")
    after_alpha = _component(after.report, "alpha")
    assert (before_alpha.module_count, after_alpha.module_count) == (3, 3)
    assert (before_alpha.internal_edges, after_alpha.internal_edges) == (1, 3)
    assert before_alpha.relational_cohesion == pytest.approx(2 / 3)
    assert after_alpha.relational_cohesion == pytest.approx(4 / 3)
    assert before_alpha.internal_dependency_density == pytest.approx(1 / 6)
    assert after_alpha.internal_dependency_density == 0.5
    # Neither side has a cross-component edge, so the share stays saturated.
    assert (before_alpha.internal_edge_share, after_alpha.internal_edge_share) == (1.0, 1.0)
    assert _boundaries(after.report) == ()


def test_fixture_g_cohesion_decrease_by_reach() -> None:
    """Fixture G: alpha holds three modules and trades an internal edge for reach."""
    configuration = (
        ComponentConfig("alpha", ("src/pkg/a.py", "src/pkg/b.py", "src/pkg/c.py")),
        ComponentConfig("beta", ("src/pkg/d.py",)),
    )
    before = _side(FIXTURE_G_BEFORE, configuration)
    after = _side(FIXTURE_G_AFTER, configuration)
    assert before.modules == ("pkg", "pkg.a", "pkg.b", "pkg.c", "pkg.d")
    assert after.modules == before.modules
    assert before.edges == (("pkg.a", "pkg.b"), ("pkg.b", "pkg.c"), ("pkg.c", "pkg.a"))
    assert after.edges == (("pkg.a", "pkg.b"), ("pkg.b", "pkg.c"), ("pkg.c", "pkg.d"))
    before_alpha = _component(before.report, "alpha")
    after_alpha = _component(after.report, "alpha")
    assert (before_alpha.module_count, after_alpha.module_count) == (3, 3)
    assert (before_alpha.internal_edges, after_alpha.internal_edges) == (3, 2)
    assert before_alpha.relational_cohesion == pytest.approx(4 / 3)
    assert after_alpha.relational_cohesion == 1.0
    assert before_alpha.internal_dependency_density == 0.5
    assert after_alpha.internal_dependency_density == pytest.approx(1 / 3)
    assert before_alpha.internal_edge_share == 1.0
    assert after_alpha.internal_edge_share == pytest.approx(2 / 3)
    assert (before_alpha.efferent, before_alpha.outgoing_edges) == (0, 0)
    assert (after_alpha.efferent, after_alpha.outgoing_edges) == (1, 1)
    assert _component(after.report, "beta").afferent == 1
    assert _boundaries(before.report) == ()
    assert _boundaries(after.report) == (("alpha", "beta", 1),)
