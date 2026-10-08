"""Pure pattern checks over the loaded configuration and snapshot reports."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from fnmatch import fnmatchcase

from .model import ComponentSpec, ScopeSpec


@dataclass(frozen=True, slots=True)
class GuardFailure:
    pattern: str
    detail: str


def patterns(components: Iterable[ComponentSpec]) -> tuple[str, ...]:
    return tuple(pattern for component in components for pattern in component.patterns)


def check_rooting(
    components: Iterable[ComponentSpec], scope: ScopeSpec
) -> tuple[GuardFailure, ...]:
    """Require a literal, declared repository prefix on every pattern."""
    prefixes = tuple(root.prefix for root in scope.implementation_roots)
    return tuple(
        GuardFailure(pattern, "no declared implementation root prefix")
        for pattern in patterns(components)
        if not pattern.startswith(prefixes)
    )


def check_containment(
    components: Iterable[ComponentSpec],
    scope: ScopeSpec,
    resolved_include_paths: Iterable[str],
    unmatched_patterns: Iterable[str],
) -> tuple[GuardFailure, ...]:
    """A root absent at this commit requires all its patterns to be unmatched."""
    resolved = set(resolved_include_paths)
    unmatched = set(unmatched_patterns)
    failures: list[GuardFailure] = []
    for pattern in patterns(components):
        for root in scope.implementation_roots:
            if pattern.startswith(root.prefix) and root.include_path not in resolved:
                if pattern not in unmatched:
                    failures.append(GuardFailure(
                        pattern,
                        f"root {root.prefix} ({root.include_path}) resolved away "
                        "but pattern is not unmatched",
                    ))
                break
    return tuple(failures)


def check_union_coverage(
    components: Iterable[ComponentSpec],
    scope: ScopeSpec,
    unmatched_by_snapshot: Iterable[Iterable[str]],
) -> tuple[GuardFailure, ...]:
    """Every ordinary pattern must match in at least one snapshot."""
    snapshots = tuple(set(items) for items in unmatched_by_snapshot)
    if not snapshots:
        return (GuardFailure("*", "no snapshot reports supplied"),)
    return tuple(
        GuardFailure(pattern, "unmatched in every snapshot")
        for pattern in patterns(components)
        if all(pattern in unmatched for unmatched in snapshots)
        and not any(root.post_rewrite_only and pattern.startswith(root.prefix)
                    for root in scope.implementation_roots)
    )


def check_pairwise_overlap(
    components: Iterable[ComponentSpec], module_paths: Iterable[str]
) -> tuple[GuardFailure, ...]:
    """Detect competing component claims on known module paths using Assay's matcher."""
    components = tuple(components)
    failures: list[GuardFailure] = []
    for path in module_paths:
        claimants = [component.name for component in components
                     if any(fnmatchcase(path, pattern) for pattern in component.patterns)]
        if len(claimants) > 1:
            failures.append(GuardFailure(path, f"claimed by {', '.join(claimants)}"))
    return tuple(failures)
