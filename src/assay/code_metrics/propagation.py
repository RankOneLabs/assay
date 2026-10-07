"""Transitive module visibility without a dense reachability matrix."""

from __future__ import annotations

from collections import defaultdict

from .models import ModuleGraph, ModuleVisibilityV4, PropagationReportV4


def analyze_propagation(graph: ModuleGraph) -> PropagationReportV4:
    """Count each node's reachable set, then discard that set before the next node."""
    nodes = tuple(sorted(entry.module for entry in graph.modules))
    if not nodes:
        return PropagationReportV4(module_visibility=(), propagation_cost=None)
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        adjacency[edge.importer].append(edge.imported)
    neighbors = {module: tuple(sorted(set(adjacency[module]))) for module in nodes}
    reached_by = dict.fromkeys(nodes, 0)
    reaches: dict[str, int] = {}
    for module in nodes:
        visible = {module}
        pending = [module]
        while pending:
            current = pending.pop()
            for target in neighbors[current]:
                if target not in visible:
                    visible.add(target)
                    pending.append(target)
        reaches[module] = len(visible)
        for target in visible:
            reached_by[target] += 1
    # Visibility counts include the module itself, as propagation cost does.
    return PropagationReportV4(
        module_visibility=tuple(
            ModuleVisibilityV4(
                module=module,
                reaches=reaches[module],
                reached_by=reached_by[module],
                fan_out_visibility=reaches[module] / len(nodes),
                fan_in_visibility=reached_by[module] / len(nodes),
            )
            for module in nodes
        ),
        propagation_cost=sum(reaches.values()) / (len(nodes) ** 2),
    )
