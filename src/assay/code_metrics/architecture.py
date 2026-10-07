"""Absolute architecture reports and their comparison, from module graphs alone."""

from __future__ import annotations

from collections.abc import Sequence

from .components import ComponentConfig, analyze_components
from .cycles import analyze_cycles
from .models import (
    ArchitectureDeltasV2,
    ArchitectureReportV4,
    BoundaryPairDelta,
    ComponentDelta,
    ComponentMetricDeltas,
    CountDelta,
    CrossComponentEdgeV2,
    ModuleCouplingDeltaV2,
    ModuleGraphV2,
    RatioDelta,
    StructuralChangesV5,
    SystemArchitectureDeltas,
)
from .propagation import analyze_propagation


def analyze_architecture(
    graph: ModuleGraphV2,
    configuration: Sequence[ComponentConfig],
    *,
    require_matches: bool = True,
) -> ArchitectureReportV4:
    """Assemble coupling, cycle, propagation, and graph-count evidence for one graph."""
    components = analyze_components(graph, configuration, require_matches=require_matches)
    return ArchitectureReportV4(
        graph=graph,
        module_count=len(graph.modules),
        first_party_edge_count=len(graph.edges),
        cross_component_edge_count=sum(pair.edge_count for pair in components.boundaries),
        module_coupling=components.module_coupling,
        component_coupling=components.component_coupling,
        module_components=components.module_components,
        boundaries=components.boundaries,
        cycles=analyze_cycles(graph),
        propagation=analyze_propagation(graph),
    )


def _count(before: int, after: int) -> CountDelta:
    return CountDelta(before=before, after=after, delta=after - before)


def _ratio(before: float | None, after: float | None) -> RatioDelta:
    delta = None if before is None or after is None else after - before
    return RatioDelta(before=before, after=after, delta=delta)


def compare_architecture(
    before: ArchitectureReportV4, after: ArchitectureReportV4
) -> ArchitectureDeltasV2:
    """Pair each side's scalars; a component or module on one side only has no entry."""
    system = SystemArchitectureDeltas(
        propagation_cost=_ratio(
            before.propagation.propagation_cost, after.propagation.propagation_cost
        ),
        first_party_edge_count=_count(before.first_party_edge_count, after.first_party_edge_count),
        cross_component_edge_count=_count(
            before.cross_component_edge_count, after.cross_component_edge_count
        ),
        cyclic_scc_count=_count(before.cycles.cyclic_scc_count, after.cycles.cyclic_scc_count),
        cyclic_module_count=_count(
            before.cycles.cyclic_module_count, after.cycles.cyclic_module_count
        ),
        largest_cyclic_scc_size=_count(
            before.cycles.largest_cyclic_scc_size, after.cycles.largest_cyclic_scc_size
        ),
    )
    old_components = {item.component: item for item in before.component_coupling}
    new_components = {item.component: item for item in after.component_coupling}
    components = []
    for name in sorted(old_components.keys() & new_components.keys()):
        old, new = old_components[name], new_components[name]
        components.append(
            ComponentDelta(
                component=name,
                metrics=ComponentMetricDeltas(
                    afferent=_count(old.afferent, new.afferent),
                    efferent=_count(old.efferent, new.efferent),
                    instability=_ratio(old.instability, new.instability),
                    internal_edges=_count(old.internal_edges, new.internal_edges),
                    incoming_edges=_count(old.incoming_edges, new.incoming_edges),
                    outgoing_edges=_count(old.outgoing_edges, new.outgoing_edges),
                    relational_cohesion=_ratio(old.relational_cohesion, new.relational_cohesion),
                    internal_dependency_density=_ratio(
                        old.internal_dependency_density, new.internal_dependency_density
                    ),
                    internal_edge_share=_ratio(old.internal_edge_share, new.internal_edge_share),
                ),
            )
        )
    old_modules = {item.module: item for item in before.module_coupling}
    new_modules = {item.module: item for item in after.module_coupling}
    modules = tuple(
        ModuleCouplingDeltaV2(
            module=name,
            fan_in=_count(old_modules[name].fan_in, new_modules[name].fan_in),
            fan_out=_count(old_modules[name].fan_out, new_modules[name].fan_out),
        )
        for name in sorted(old_modules.keys() & new_modules.keys())
    )
    # A boundary keeps its identity at zero edges, so a missing side counts 0.
    old_pairs = {
        (pair.importer_component, pair.imported_component): pair.edge_count
        for pair in before.boundaries
    }
    new_pairs = {
        (pair.importer_component, pair.imported_component): pair.edge_count
        for pair in after.boundaries
    }
    boundaries = tuple(
        BoundaryPairDelta(
            importer_component=source,
            imported_component=target,
            before=old_pairs.get((source, target), 0),
            after=new_pairs.get((source, target), 0),
            delta=new_pairs.get((source, target), 0) - old_pairs.get((source, target), 0),
        )
        for source, target in sorted(old_pairs.keys() | new_pairs.keys())
    )
    return ArchitectureDeltasV2(
        system=system, components=tuple(components), modules=modules, boundaries=boundaries
    )


def cross_component_edges(report: ArchitectureReportV4) -> frozenset[CrossComponentEdgeV2]:
    """Edges whose ends belong to different components, labeled with both owners."""
    owner = {entry.module: entry.component for entry in report.module_components}
    return frozenset(
        CrossComponentEdgeV2(
            importer=edge.importer,
            imported=edge.imported,
            importer_component=owner[edge.importer],
            imported_component=owner[edge.imported],
        )
        for edge in report.graph.edges
        if owner[edge.importer] != owner[edge.imported]
    )


def _cross_component_order(edge: CrossComponentEdgeV2) -> tuple[str, str, str, str]:
    return (edge.importer_component, edge.imported_component, edge.importer, edge.imported)


def structural_changes(
    before: ArchitectureReportV4, after: ArchitectureReportV4
) -> StructuralChangesV5:
    """Set differences of modules, edges, components, cyclic SCCs, and boundary edges.

    A cross-component edge is identified by both ends and both owners, so an
    edge whose owners change between sides is removed with the old owners and
    added with the new ones.
    """
    old_modules = {entry.module for entry in before.graph.modules}
    new_modules = {entry.module for entry in after.graph.modules}
    old_edges, new_edges = set(before.graph.edges), set(after.graph.edges)
    old_components = {entry.component for entry in before.component_coupling}
    new_components = {entry.component for entry in after.component_coupling}
    old_cycles = {item.modules for item in before.cycles.components if item.is_cyclic}
    new_cycles = {item.modules for item in after.cycles.components if item.is_cyclic}
    old_boundary, new_boundary = cross_component_edges(before), cross_component_edges(after)
    return StructuralChangesV5(
        modules_added=tuple(sorted(new_modules - old_modules)),
        modules_removed=tuple(sorted(old_modules - new_modules)),
        edges_added=tuple(
            sorted(new_edges - old_edges, key=lambda item: (item.importer, item.imported))
        ),
        edges_removed=tuple(
            sorted(old_edges - new_edges, key=lambda item: (item.importer, item.imported))
        ),
        components_added=tuple(sorted(new_components - old_components)),
        components_removed=tuple(sorted(old_components - new_components)),
        cycles_created=tuple(sorted(new_cycles - old_cycles)),
        cycles_resolved=tuple(sorted(old_cycles - new_cycles)),
        cross_component_edges_added=tuple(
            sorted(new_boundary - old_boundary, key=_cross_component_order)
        ),
        cross_component_edges_removed=tuple(
            sorted(old_boundary - new_boundary, key=_cross_component_order)
        ),
    )
