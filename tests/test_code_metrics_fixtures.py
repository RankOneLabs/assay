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
    FIXTURE_K_AFTER,
    FIXTURE_K_BEFORE,
)

from assay.code_metrics.architecture import (
    analyze_architecture,
    compare_architecture,
    structural_changes,
)
from assay.code_metrics.components import ComponentConfig
from assay.code_metrics.cycles import analyze_cycles
from assay.code_metrics.graph import build_module_graph
from assay.code_metrics.models import (
    METRICS,
    ArchitectureDeltas,
    ArchitectureReportV3,
    BoundaryPair,
    BoundaryPairDelta,
    ComponentCouplingV3,
    ComponentMetricDeltas,
    CycleReportV3,
    DetailedStructuralChanges,
    ModuleCouplingDelta,
    ModuleCouplingV3,
    ModuleVisibilityV3,
    PropagationReportV3,
    Snapshot,
    StructuralChangesV4,
    SystemArchitectureDeltas,
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
    _GraphEvidenceCase(
        "FIXTURE_K_BEFORE",
        FIXTURE_K_BEFORE,
        _FOUR_LEAF,
        (("pkg.a", "pkg.b"), ("pkg.b", "pkg.c"), ("pkg.d", "pkg.a")),
        "propagation",
        11 / 25,
    ),
    _GraphEvidenceCase(
        "FIXTURE_K_AFTER",
        FIXTURE_K_AFTER,
        _FOUR_LEAF,
        (("pkg.a", "pkg.b"), ("pkg.b", "pkg.c"), ("pkg.b", "pkg.d"), ("pkg.d", "pkg.a")),
        "propagation",
        14 / 25,
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


_ALPHA_AB_BETA_CD = (
    ComponentConfig("alpha", ("src/pkg/a.py", "src/pkg/b.py")),
    ComponentConfig("beta", ("src/pkg/c.py", "src/pkg/d.py")),
)


def test_every_architecture_metric_has_a_specific_fixture() -> None:
    coupling_graph, _ = build_module_graph(FIXTURE_COUPLING)
    coupling = analyze_architecture(coupling_graph, _ALPHA_AB_BETA_CD)
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
        "architecture.module_count": ("FIXTURE_COUPLING", coupling.module_count, 5),
        "architecture.first_party_edge_count": (
            "FIXTURE_COUPLING",
            coupling.first_party_edge_count,
            3,
        ),
        "architecture.cross_component_edge_count": (
            "FIXTURE_COUPLING",
            coupling.cross_component_edge_count,
            2,
        ),
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
        "cycles.scc_count": ("FIXTURE_C_AFTER", cycles.scc_count, 2),
        "cycles.cyclic_scc_count": ("FIXTURE_C_AFTER", cycles.cyclic_scc_count, 1),
        "cycles.cyclic_module_count": ("FIXTURE_C_AFTER", cycles.cyclic_module_count, 3),
        "cycles.largest_cyclic_scc_size": ("FIXTURE_C_AFTER", cycles.largest_cyclic_scc_size, 3),
        "propagation.module_visibility.reaches": ("FIXTURE_A", visibility.reaches, 3),
        "propagation.module_visibility.reached_by": ("FIXTURE_A", visibility.reached_by, 1),
        "propagation.module_visibility.fan_out_visibility": (
            "FIXTURE_A",
            visibility.fan_out_visibility,
            0.75,
        ),
        "propagation.module_visibility.fan_in_visibility": (
            "FIXTURE_A",
            visibility.fan_in_visibility,
            0.25,
        ),
        "propagation.propagation_cost": ("FIXTURE_A", propagation.propagation_cost, 7 / 16),
    }
    expected_fields = {
        *(
            f"architecture.{name}"
            for name, field in ArchitectureReportV3.model_fields.items()
            if field.annotation is int
        ),
        *(
            f"module_coupling.{field}"
            for field in ModuleCouplingV3.model_fields
            if field != "module"
        ),
        *(
            f"component_coupling.{field}"
            for field in ComponentCouplingV3.model_fields
            if field not in {"component", "modules"}
        ),
        *(f"boundaries.{field}" for field in BoundaryPair.model_fields if field == "edge_count"),
        *(f"cycles.{field}" for field in CycleReportV3.model_fields if field != "components"),
        *(
            f"propagation.module_visibility.{field}"
            for field in ModuleVisibilityV3.model_fields
            if field != "module"
        ),
        *(
            f"propagation.{field}"
            for field in PropagationReportV3.model_fields
            if field != "module_visibility"
        ),
    }
    assert set(coverage) == expected_fields
    for metric, (fixture, actual, expected) in coverage.items():
        assert fixture in {"FIXTURE_A", "FIXTURE_C_AFTER", "FIXTURE_COUPLING"}
        assert actual == expected, (metric, fixture)


def test_every_architecture_delta_has_a_specific_fixture() -> None:
    """Fixture K pins every delta field, each to its before, after, and delta."""
    before_graph, _ = build_module_graph(FIXTURE_K_BEFORE)
    after_graph, _ = build_module_graph(FIXTURE_K_AFTER)
    before = analyze_architecture(before_graph, _ALPHA_AB_BETA_CD)
    after = analyze_architecture(after_graph, _ALPHA_AB_BETA_CD)
    deltas = compare_architecture(before, after)
    changes = structural_changes(before, after)
    alpha = next(item.metrics for item in deltas.components if item.component == "alpha")
    module = next(item for item in deltas.modules if item.module == "pkg.b")
    boundary = next(item for item in deltas.boundaries if item.importer_component == "alpha")

    def triple(value: object) -> tuple[object, object, object]:
        return (value.before, value.after, value.delta)  # type: ignore[attr-defined]

    coverage = {
        "system.propagation_cost": (
            triple(deltas.system.propagation_cost),
            pytest.approx((11 / 25, 14 / 25, 3 / 25)),
        ),
        "system.first_party_edge_count": (triple(deltas.system.first_party_edge_count), (3, 4, 1)),
        "system.cross_component_edge_count": (
            triple(deltas.system.cross_component_edge_count),
            (2, 3, 1),
        ),
        "system.cyclic_scc_count": (triple(deltas.system.cyclic_scc_count), (0, 1, 1)),
        "system.cyclic_module_count": (triple(deltas.system.cyclic_module_count), (0, 3, 3)),
        "system.largest_cyclic_scc_size": (
            triple(deltas.system.largest_cyclic_scc_size),
            (0, 3, 3),
        ),
        "components.afferent": (triple(alpha.afferent), (1, 1, 0)),
        "components.efferent": (triple(alpha.efferent), (1, 2, 1)),
        "components.instability": (
            triple(alpha.instability),
            pytest.approx((1 / 2, 2 / 3, 1 / 6)),
        ),
        "components.internal_edges": (triple(alpha.internal_edges), (1, 1, 0)),
        "components.incoming_edges": (triple(alpha.incoming_edges), (1, 1, 0)),
        "components.outgoing_edges": (triple(alpha.outgoing_edges), (1, 2, 1)),
        "components.relational_cohesion": (triple(alpha.relational_cohesion), (1.0, 1.0, 0.0)),
        "components.internal_dependency_density": (
            triple(alpha.internal_dependency_density),
            (0.5, 0.5, 0.0),
        ),
        "components.internal_edge_share": (
            triple(alpha.internal_edge_share),
            pytest.approx((1 / 3, 1 / 4, -1 / 12)),
        ),
        "modules.fan_in": (triple(module.fan_in), (1, 1, 0)),
        "modules.fan_out": (triple(module.fan_out), (1, 2, 1)),
        "boundaries.edge_count": (triple(boundary), (1, 2, 1)),
        "structural_changes.cross_component_edges_added": (
            tuple(
                (e.importer, e.imported, e.importer_component, e.imported_component)
                for e in changes.cross_component_edges_added
            ),
            (("pkg.b", "pkg.d", "alpha", "beta"),),
        ),
        "structural_changes.cross_component_edges_removed": (
            changes.cross_component_edges_removed,
            (),
        ),
    }
    expected_fields = {
        *(f"system.{field}" for field in SystemArchitectureDeltas.model_fields),
        *(f"components.{field}" for field in ComponentMetricDeltas.model_fields),
        *(f"modules.{field}" for field in ModuleCouplingDelta.model_fields if field != "module"),
        "boundaries.edge_count",
        *(
            f"structural_changes.{field}"
            for field in StructuralChangesV4.model_fields
            if field not in DetailedStructuralChanges.model_fields
        ),
    }
    assert set(ArchitectureDeltas.model_fields) == {"system", "components", "modules", "boundaries"}
    # A boundary delta carries one edge count's before, after, and delta.
    assert set(BoundaryPairDelta.model_fields) == {
        "importer_component",
        "imported_component",
        "before",
        "after",
        "delta",
    }
    assert set(coverage) == expected_fields
    for field, (actual, expected) in coverage.items():
        assert actual == expected, field
