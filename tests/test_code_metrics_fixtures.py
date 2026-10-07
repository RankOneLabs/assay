"""Audit the graph evidence carried by the supplied named fixtures."""

import json
from pathlib import Path

import pytest
from code_metrics_fixtures import (
    FIXTURE_A,
    FIXTURE_C_AFTER,
    FIXTURE_C_BEFORE,
    FIXTURE_COUPLING,
    FIXTURE_D_AFTER,
    FIXTURE_D_BEFORE,
    FIXTURE_H,
    FIXTURE_I,
    FIXTURE_J,
)

from assay.code_metrics.components import ComponentConfig, analyze_components
from assay.code_metrics.cycles import analyze_cycles
from assay.code_metrics.graph import build_module_graph
from assay.code_metrics.models import (
    METRICS,
    BoundaryPair,
    ComponentCoupling,
    CycleReport,
    ModuleCoupling,
    ModuleVisibility,
    PropagationReport,
    Snapshot,
)
from assay.code_metrics.propagation import analyze_propagation


@pytest.mark.parametrize(
    ("snapshot", "modules", "edges", "scalar"),
    [
        (
            FIXTURE_A,
            ("pkg", "pkg.a", "pkg.b", "pkg.c"),
            (("pkg.a", "pkg.b"), ("pkg.b", "pkg.c")),
            7 / 16,
        ),
        (
            FIXTURE_C_BEFORE,
            ("pkg", "pkg.a", "pkg.b", "pkg.c"),
            (("pkg.a", "pkg.b"), ("pkg.b", "pkg.c")),
            0,
        ),
        (
            FIXTURE_C_AFTER,
            ("pkg", "pkg.a", "pkg.b", "pkg.c"),
            (("pkg.a", "pkg.b"), ("pkg.b", "pkg.c"), ("pkg.c", "pkg.a")),
            1,
        ),
        (
            FIXTURE_D_BEFORE,
            ("pkg", "pkg.a", "pkg.b", "pkg.c"),
            (("pkg.a", "pkg.b"), ("pkg.b", "pkg.c"), ("pkg.c", "pkg.a")),
            1,
        ),
        (
            FIXTURE_D_AFTER,
            ("pkg", "pkg.a", "pkg.b", "pkg.c"),
            (("pkg.a", "pkg.b"), ("pkg.b", "pkg.c")),
            0,
        ),
        (FIXTURE_H, ("pkg", "pkg.isolated"), (), 0),
        (FIXTURE_I, ("pkg", "pkg.a"), (), 0),
        (FIXTURE_J, ("pkg", "pkg.a", "pkg.b"), (("pkg.a", "pkg.b"),), 0),
        (
            FIXTURE_COUPLING,
            ("pkg", "pkg.a", "pkg.b", "pkg.c", "pkg.d"),
            (("pkg.a", "pkg.b"), ("pkg.b", "pkg.c"), ("pkg.d", "pkg.a")),
            0,
        ),
    ],
)
def test_fixture_graph_evidence(
    snapshot: Snapshot,
    modules: tuple[str, ...],
    edges: tuple[tuple[str, str], ...],
    scalar: float,
) -> None:
    graph, _ = build_module_graph(snapshot)
    assert tuple(entry.module for entry in graph.modules) == modules
    assert tuple((edge.importer, edge.imported) for edge in graph.edges) == edges
    if snapshot is FIXTURE_A:
        assert analyze_propagation(graph).propagation_cost == pytest.approx(scalar)
    else:
        assert analyze_cycles(graph).cyclic_component_count == scalar


def test_every_public_metric_has_a_specific_golden_case() -> None:
    golden = json.loads(
        (Path(__file__).parent / "fixtures/code_metrics_golden.json").read_text(encoding="utf-8")
    )
    coverage = {
        "radon.sloc": "inlined",
        "radon.lloc": "inlined",
        "radon.cc": "inlined",
        "radon.halstead_volume": "inlined",
        "radon.mi": "inlined",
        "complexipy.cognitive": "inlined",
        "grimp.imports": "inlined",
        "ruff.violations": "single_module",
        "ruff.magic_values": "single_module",
        "mypy.errors": "delegating",
        "jscpd.clones": "inlined",
        "jscpd.duplicated_lines": "inlined",
        "new_lines": "delegating",
        "new_duplicated_lines": "inlined",
        "new_max_nesting_depth": "inlined",
    }
    assert set(coverage) == set(METRICS)
    for metric, case in coverage.items():
        assert metric in golden[case]["metrics"], (metric, case)


def test_every_architecture_metric_has_a_specific_fixture() -> None:
    coupling_graph, _ = build_module_graph(FIXTURE_COUPLING)
    coupling = analyze_components(
        coupling_graph,
        (
            ComponentConfig("alpha", ("src/pkg/a.py", "src/pkg/b.py")),
            ComponentConfig("beta", ("src/pkg/c.py", "src/pkg/d.py")),
        ),
    )
    module = next(item for item in coupling.module_coupling if item.module == "pkg.a")
    component = next(item for item in coupling.component_coupling if item.component == "alpha")
    boundary = next(item for item in coupling.boundaries if item.importer_component == "alpha")
    cycle_graph, _ = build_module_graph(FIXTURE_C_AFTER)
    cycles = analyze_cycles(cycle_graph)
    chain_graph, _ = build_module_graph(FIXTURE_A)
    propagation = analyze_propagation(chain_graph)
    visibility = next(item for item in propagation.module_visibility if item.module == "pkg.a")

    # Each key is a numeric or derived architecture field; the fixture name
    # identifies the snapshot whose specific scalar is asserted here.
    coverage = {
        "module_coupling.fan_in": ("FIXTURE_COUPLING", module.fan_in, 1),
        "module_coupling.fan_out": ("FIXTURE_COUPLING", module.fan_out, 1),
        "component_coupling.afferent": ("FIXTURE_COUPLING", component.afferent, 1),
        "component_coupling.efferent": ("FIXTURE_COUPLING", component.efferent, 1),
        "component_coupling.instability": ("FIXTURE_COUPLING", component.instability, 0.5),
        "component_coupling.internal_edges": ("FIXTURE_COUPLING", component.internal_edges, 1),
        "component_coupling.incoming_edges": ("FIXTURE_COUPLING", component.incoming_edges, 1),
        "component_coupling.outgoing_edges": ("FIXTURE_COUPLING", component.outgoing_edges, 1),
        "component_coupling.module_count": ("FIXTURE_COUPLING", component.module_count, 2),
        "component_coupling.relational_cohesion": (
            "FIXTURE_COUPLING",
            component.relational_cohesion,
            1.0,
        ),
        "component_coupling.internal_dependency_density": (
            "FIXTURE_COUPLING",
            component.internal_dependency_density,
            0.5,
        ),
        "component_coupling.internal_edge_share": (
            "FIXTURE_COUPLING",
            component.internal_edge_share,
            1 / 3,
        ),
        "boundaries.edge_count": ("FIXTURE_COUPLING", boundary.edge_count, 1),
        "cycles.cyclic_component_count": ("FIXTURE_C_AFTER", cycles.cyclic_component_count, 1),
        "cycles.modules_in_cycles": (
            "FIXTURE_C_AFTER",
            cycles.modules_in_cycles,
            ("pkg.a", "pkg.b", "pkg.c"),
        ),
        "propagation.module_visibility.reaches": ("FIXTURE_A", visibility.reaches, 3),
        "propagation.module_visibility.reached_by": ("FIXTURE_A", visibility.reached_by, 1),
        "propagation.propagation_cost": ("FIXTURE_A", propagation.propagation_cost, 7 / 16),
    }
    expected_fields = {
        *(f"module_coupling.{field}" for field in ModuleCoupling.model_fields if field != "module"),
        *(
            f"component_coupling.{field}"
            for field in ComponentCoupling.model_fields
            if field not in {"component", "modules"}
        ),
        *(f"boundaries.{field}" for field in BoundaryPair.model_fields if field == "edge_count"),
        *(f"cycles.{field}" for field in CycleReport.model_fields if field != "components"),
        *(
            f"propagation.module_visibility.{field}"
            for field in ModuleVisibility.model_fields
            if field != "module"
        ),
        *(
            f"propagation.{field}"
            for field in PropagationReport.model_fields
            if field != "module_visibility"
        ),
    }
    assert set(coverage) == expected_fields
    for metric, (fixture, actual, expected) in coverage.items():
        assert fixture in {"FIXTURE_A", "FIXTURE_C_AFTER", "FIXTURE_COUPLING"}
        assert actual == expected, (metric, fixture)
