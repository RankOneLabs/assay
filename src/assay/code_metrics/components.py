"""Component assignment and coupling metrics from a ModuleGraph."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase

from .errors import AmbiguousComponentConfig, ConfigurationError, EmptyComponentPattern
from .models import (
    BoundaryPair,
    ComponentCoupling,
    ComponentMetricsReport,
    ModuleComponent,
    ModuleCoupling,
    ModuleEntry,
    ModuleGraph,
)


@dataclass(frozen=True)
class ComponentConfig:
    name: str
    patterns: tuple[str, ...]


def _target(entry: ModuleEntry) -> str:
    # A namespace entry has no filesystem path; its dotted prefix is the
    # only truthful target for matching.
    return entry.path if entry.path is not None else entry.module


def require_pattern_matches(
    graphs: Sequence[ModuleGraph], configuration: Sequence[ComponentConfig]
) -> None:
    """Reject a pattern that matches no module in any of *graphs*."""
    targets = [_target(entry) for graph in graphs for entry in graph.modules]
    for component in configuration:
        for pattern in component.patterns:
            if not any(fnmatchcase(target, pattern) for target in targets):
                raise EmptyComponentPattern(
                    f"component {component.name} pattern {pattern!r} matched zero modules"
                )


def assign_components(
    graph: ModuleGraph,
    configuration: Sequence[ComponentConfig],
    *,
    require_matches: bool = True,
) -> tuple[ModuleComponent, ...]:
    """Resolve path globs, preserving real paths and assigning every module once.

    A comparison passes ``require_matches=False`` and checks the patterns
    against both snapshots, so a component may exist on only one side.
    """
    if any(item.name == "unassigned" for item in configuration):
        raise ConfigurationError("'unassigned' is a reserved component name")
    names = [item.name for item in configuration]
    if len(names) != len(set(names)):
        raise ConfigurationError("component names must be unique")
    assigned: list[ModuleComponent] = []
    for entry in sorted(graph.modules, key=lambda item: item.module):
        target = _target(entry)
        claimants = [
            component.name
            for component in configuration
            if any(fnmatchcase(target, pattern) for pattern in component.patterns)
        ]
        if len(claimants) > 1:
            raise AmbiguousComponentConfig(
                f"module {entry.module} claimed by components {', '.join(sorted(claimants))}"
            )
        assigned.append(
            ModuleComponent(
                module=entry.module,
                path=entry.path,
                component=claimants[0] if claimants else "unassigned",
            )
        )
    if require_matches:
        require_pattern_matches((graph,), configuration)
    return tuple(assigned)


def analyze_components(
    graph: ModuleGraph,
    configuration: Sequence[ComponentConfig],
    *,
    require_matches: bool = True,
) -> ComponentMetricsReport:
    """Count distinct neighboring modules and raw edges for each component."""
    assignments = assign_components(graph, configuration, require_matches=require_matches)
    owner = {entry.module: entry.component for entry in assignments}
    members: dict[str, list[str]] = defaultdict(list)
    for entry in assignments:
        members[entry.component].append(entry.module)
    incoming_modules: dict[str, set[str]] = defaultdict(set)
    outgoing_modules: dict[str, set[str]] = defaultdict(set)
    internal: Counter[str] = Counter()
    incoming: Counter[str] = Counter()
    outgoing: Counter[str] = Counter()
    boundary: Counter[tuple[str, str]] = Counter()
    fan_in: Counter[str] = Counter()
    fan_out: Counter[str] = Counter()
    for edge in graph.edges:
        importer, imported = edge.importer, edge.imported
        fan_out[importer] += 1
        fan_in[imported] += 1
        source, target = owner[importer], owner[imported]
        if source == target:
            internal[source] += 1
        else:
            outgoing[source] += 1
            incoming[target] += 1
            outgoing_modules[source].add(imported)
            incoming_modules[target].add(importer)
            boundary[(source, target)] += 1
    coupling = []
    for name in sorted(members):
        n = len(members[name])
        r = internal[name]
        ca, ce = len(incoming_modules[name]), len(outgoing_modules[name])
        total_edges = r + incoming[name] + outgoing[name]
        coupling.append(
            ComponentCoupling(
                component=name,
                modules=tuple(members[name]),
                afferent=ca,
                efferent=ce,
                instability=ce / (ca + ce) if ca + ce else None,
                internal_edges=r,
                incoming_edges=incoming[name],
                outgoing_edges=outgoing[name],
                module_count=n,
                relational_cohesion=(r + 1) / n,
                internal_dependency_density=r / (n * (n - 1)) if n > 1 else None,
                internal_edge_share=r / total_edges if total_edges else None,
            )
        )
    return ComponentMetricsReport(
        module_coupling=tuple(
            ModuleCoupling(
                module=entry.module, fan_in=fan_in[entry.module], fan_out=fan_out[entry.module]
            )
            for entry in assignments
        ),
        component_coupling=tuple(coupling),
        module_components=assignments,
        boundaries=tuple(
            BoundaryPair(importer_component=source, imported_component=target, edge_count=count)
            for (source, target), count in sorted(boundary.items())
        ),
    )
