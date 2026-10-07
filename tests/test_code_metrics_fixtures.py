"""Audit the graph evidence carried by the supplied named fixtures."""

import json
from pathlib import Path
from typing import Literal, NamedTuple

import code_metrics_fixtures
import pytest
from code_metrics_fixtures import (
    FIXTURE_A,
    FIXTURE_B_AFTER,
    FIXTURE_B_BEFORE,
    FIXTURE_C_AFTER,
    FIXTURE_C_BEFORE,
    FIXTURE_COUPLING,
    FIXTURE_D_AFTER,
    FIXTURE_D_BEFORE,
    FIXTURE_E_AFTER,
    FIXTURE_E_BEFORE,
    FIXTURE_F_AFTER,
    FIXTURE_F_BEFORE,
    FIXTURE_G_AFTER,
    FIXTURE_G_BEFORE,
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


class _GraphEvidenceCase(NamedTuple):
    """One named fixture's full graph evidence and the graph scalar it pins.

    Component-scoped scalars - Ca, Ce, cohesion, density, edge share - are
    pinned in test_code_metrics_components.py, which needs a component
    configuration this table deliberately does not carry.
    """

    name: str
    snapshot: Snapshot
    modules: tuple[str, ...]
    edges: tuple[tuple[str, str], ...]
    metric: Literal["propagation", "cycles"]
    scalar: float


_CHAIN = ("pkg", "pkg.a", "pkg.b", "pkg.c")
_FOUR_LEAF = ("pkg", "pkg.a", "pkg.b", "pkg.c", "pkg.d")
_LINEAR = (("pkg.a", "pkg.b"), ("pkg.b", "pkg.c"))
_TRIANGLE = (("pkg.a", "pkg.b"), ("pkg.b", "pkg.c"), ("pkg.c", "pkg.a"))
_FORK = (("pkg.a", "pkg.b"), ("pkg.a", "pkg.c"))
_SINGLE = (("pkg.a", "pkg.b"),)
_RELAY = (("pkg.a", "pkg.b"), ("pkg.b", "pkg.c"), ("pkg.c", "pkg.d"))

_GRAPH_EVIDENCE = (
    _GraphEvidenceCase("FIXTURE_A", FIXTURE_A, _CHAIN, _LINEAR, "propagation", 7 / 16),
    _GraphEvidenceCase(
        "FIXTURE_B_BEFORE", FIXTURE_B_BEFORE, _CHAIN, _SINGLE, "propagation", 5 / 16
    ),
    _GraphEvidenceCase("FIXTURE_B_AFTER", FIXTURE_B_AFTER, _CHAIN, _FORK, "propagation", 6 / 16),
    _GraphEvidenceCase("FIXTURE_C_BEFORE", FIXTURE_C_BEFORE, _CHAIN, _LINEAR, "cycles", 0),
    _GraphEvidenceCase("FIXTURE_C_AFTER", FIXTURE_C_AFTER, _CHAIN, _TRIANGLE, "cycles", 1),
    _GraphEvidenceCase("FIXTURE_D_BEFORE", FIXTURE_D_BEFORE, _CHAIN, _TRIANGLE, "cycles", 1),
    _GraphEvidenceCase("FIXTURE_D_AFTER", FIXTURE_D_AFTER, _CHAIN, _LINEAR, "cycles", 0),
    _GraphEvidenceCase(
        "FIXTURE_E_BEFORE",
        FIXTURE_E_BEFORE,
        _FOUR_LEAF,
        (("pkg.a", "pkg.b"), ("pkg.c", "pkg.d")),
        "propagation",
        7 / 25,
    ),
    _GraphEvidenceCase(
        "FIXTURE_E_AFTER", FIXTURE_E_AFTER, _FOUR_LEAF, _RELAY, "propagation", 11 / 25
    ),
    _GraphEvidenceCase("FIXTURE_F_BEFORE", FIXTURE_F_BEFORE, _CHAIN, _SINGLE, "cycles", 0),
    _GraphEvidenceCase("FIXTURE_F_AFTER", FIXTURE_F_AFTER, _CHAIN, _TRIANGLE, "cycles", 1),
    _GraphEvidenceCase("FIXTURE_G_BEFORE", FIXTURE_G_BEFORE, _FOUR_LEAF, _TRIANGLE, "cycles", 1),
    _GraphEvidenceCase("FIXTURE_G_AFTER", FIXTURE_G_AFTER, _FOUR_LEAF, _RELAY, "cycles", 0),
    _GraphEvidenceCase("FIXTURE_H", FIXTURE_H, ("pkg", "pkg.isolated"), (), "cycles", 0),
    _GraphEvidenceCase("FIXTURE_I", FIXTURE_I, ("pkg", "pkg.a"), (), "cycles", 0),
    _GraphEvidenceCase("FIXTURE_J", FIXTURE_J, ("pkg", "pkg.a", "pkg.b"), _SINGLE, "cycles", 0),
    _GraphEvidenceCase(
        "FIXTURE_COUPLING",
        FIXTURE_COUPLING,
        _FOUR_LEAF,
        (("pkg.a", "pkg.b"), ("pkg.b", "pkg.c"), ("pkg.d", "pkg.a")),
        "cycles",
        0,
    ),
)


@pytest.mark.parametrize("case", _GRAPH_EVIDENCE, ids=[case.name for case in _GRAPH_EVIDENCE])
def test_fixture_graph_evidence(case: _GraphEvidenceCase) -> None:
    graph, _ = build_module_graph(case.snapshot)
    assert tuple(entry.module for entry in graph.modules) == case.modules
    assert tuple((edge.importer, edge.imported) for edge in graph.edges) == case.edges
    if case.metric == "propagation":
        assert analyze_propagation(graph).propagation_cost == pytest.approx(case.scalar)
    else:
        assert analyze_cycles(graph).cyclic_component_count == case.scalar


def test_audit_covers_every_named_fixture() -> None:
    """A new fixture constant without an evidence row fails here, not silently."""
    declared = sorted(name for name in vars(code_metrics_fixtures) if name.startswith("FIXTURE_"))
    assert sorted(case.name for case in _GRAPH_EVIDENCE) == declared
    for case in _GRAPH_EVIDENCE:
        assert getattr(code_metrics_fixtures, case.name) is case.snapshot


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
