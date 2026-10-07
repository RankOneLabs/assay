"""Iterative strongly connected components over a module graph."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping

from .models import CycleReportV4, ModuleGraph, StronglyConnectedComponentV2


def strongly_connected_components(
    adjacency: Mapping[str, Iterable[str]],
) -> tuple[StronglyConnectedComponentV2, ...]:
    """Tarjan's algorithm with explicit traversal frames instead of recursion."""
    neighbors = {name: tuple(sorted(set(targets))) for name, targets in adjacency.items()}
    nodes = sorted(set(neighbors).union(*(set(targets) for targets in neighbors.values())))
    for node in nodes:
        neighbors.setdefault(node, ())
    indices: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    found: list[StronglyConnectedComponentV2] = []
    for root in nodes:
        if root in indices:
            continue
        frames: list[tuple[str, int]] = [(root, 0)]
        while frames:
            node, offset = frames[-1]
            if node not in indices:
                indices[node] = low[node] = len(indices)
                stack.append(node)
                on_stack.add(node)
            if offset < len(neighbors[node]):
                target = neighbors[node][offset]
                frames[-1] = (node, offset + 1)
                if target not in indices:
                    frames.append((target, 0))
                elif target in on_stack:
                    low[node] = min(low[node], indices[target])
                continue
            frames.pop()
            if frames:
                parent = frames[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == indices[node]:
                members: list[str] = []
                while True:
                    member = stack.pop()
                    on_stack.remove(member)
                    members.append(member)
                    if member == node:
                        break
                ordered = tuple(sorted(members))
                found.append(
                    StronglyConnectedComponentV2(
                        modules=ordered,
                        is_cyclic=len(ordered) > 1 or node in neighbors[node],
                    )
                )
    return tuple(sorted(found, key=lambda item: item.modules))


def analyze_cycles(graph: ModuleGraph) -> CycleReportV4:
    """Report every SCC, the modules belonging to cyclic SCCs, and their counts."""
    adjacency: dict[str, list[str]] = defaultdict(list)
    for entry in graph.modules:
        adjacency[entry.module]
    for edge in graph.edges:
        adjacency[edge.importer].append(edge.imported)
    components = strongly_connected_components(adjacency)
    cyclic = tuple(component for component in components if component.is_cyclic)
    # SCCs partition the modules, so no module repeats across cyclic SCCs.
    modules_in_cycles = tuple(
        sorted(module for component in cyclic for module in component.modules)
    )
    return CycleReportV4(
        components=components,
        cyclic_component_count=len(cyclic),
        modules_in_cycles=modules_in_cycles,
        scc_count=len(components),
        cyclic_scc_count=len(cyclic),
        cyclic_module_count=len(modules_in_cycles),
        largest_cyclic_scc_size=max((len(component.modules) for component in cyclic), default=0),
    )
