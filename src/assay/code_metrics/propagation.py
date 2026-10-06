"""Transitive module visibility without a dense reachability matrix."""

from __future__ import annotations

from collections import defaultdict

from .models import ModuleGraph, ModuleVisibility, PropagationReport


def analyze_propagation(graph: ModuleGraph) -> PropagationReport:
    """Count each node's reachable set, then discard that set before the next node."""
    nodes = tuple(sorted(entry.module for entry in graph.modules))
    if not nodes:
        return PropagationReport(module_visibility=(), propagation_cost=None)
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
    return PropagationReport(
        module_visibility=tuple(
            ModuleVisibility(module=module, reaches=reaches[module], reached_by=reached_by[module])
            for module in nodes
        ),
        propagation_cost=sum(reaches.values()) / (len(nodes) ** 2),
    )
