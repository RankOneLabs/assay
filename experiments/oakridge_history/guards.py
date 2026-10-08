"""Pure pattern checks over the loaded configuration and snapshot reports."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

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


def _collapse_stars(pattern: str) -> str:
    result: list[str] = []
    for character in pattern:
        if character != "*" or not result or result[-1] != "*":
            result.append(character)
    return "".join(result)


def _star_globs_overlap(first: str, second: str) -> bool:
    """Decide whether two literal-and-star globs accept a common path.

    Assay's ``fnmatchcase`` treats every star, including ``**``, as matching
    across ``/``. A star can consume any character or advance without one.
    """
    first = _collapse_stars(first)
    second = _collapse_stars(second)
    pending = [(0, 0)]
    visited: set[tuple[int, int]] = set()
    while pending:
        left, right = pending.pop()
        if (left, right) in visited:
            continue
        visited.add((left, right))
        if left == len(first) and right == len(second):
            return True
        if left < len(first) and first[left] == "*":
            pending.append((left + 1, right))
        if right < len(second) and second[right] == "*":
            pending.append((left, right + 1))
        if left == len(first) or right == len(second):
            continue
        if first[left] == "*" and second[right] != "*":
            pending.append((left, right + 1))
        elif second[right] == "*" and first[left] != "*":
            pending.append((left + 1, right))
        elif first[left] == second[right] and first[left] != "*":
            pending.append((left + 1, right + 1))
    return False


def check_pairwise_overlap(components: Iterable[ComponentSpec]) -> tuple[GuardFailure, ...]:
    """Reject cross-component glob overlap without sampling modules.

    Literal characters and ``*`` are checked exactly. Other fnmatch operators
    fail closed until this checker explicitly supports them.
    """
    components = tuple(components)
    failures: list[GuardFailure] = []
    for component in components:
        for pattern in component.patterns:
            if any(character in pattern for character in "?[]"):
                failures.append(GuardFailure(
                    pattern, "unsupported glob operator in static overlap check"
                ))
    if failures:
        return tuple(failures)
    for index, first in enumerate(components):
        for second in components[index + 1:]:
            for left in first.patterns:
                for right in second.patterns:
                    if _star_globs_overlap(left, right):
                        failures.append(GuardFailure(
                            left, f"overlaps {right!r} in component {second.name}; "
                            f"claimed by {first.name} and {second.name}"
                        ))
    return tuple(failures)
