"""Contributor accounts for the pilot's prefilled verification session.

The accounts contain only the public migration declaration and ownership map.
They are constructed once; presentation order is a separate operation.
"""

from __future__ import annotations

from dataclasses import dataclass

from verification_pilot.migrations import GROUPS, Migration, OwnershipGroup


@dataclass(frozen=True, slots=True)
class ContributorBlock:
    group: OwnershipGroup
    paths: tuple[str, ...]
    text: str


def contributor_blocks(migration: Migration) -> tuple[ContributorBlock, ...]:
    """Build the four ownership accounts without consulting a specimen or oracle."""
    ownership = migration.ownership_groups
    blocks: list[ContributorBlock] = []
    for group in GROUPS:
        paths = tuple(sorted(path for path, assigned in ownership.items() if assigned == group))
        if not paths:
            raise ValueError(f"{migration.name}: {group} has no assigned paths")
        text = (
            f"Contributor {group}\n"
            f"Migration: rename {migration.old_symbol} to {migration.new_symbol} "
            f"({migration.kind}).\n"
            "Assigned files:\n"
            + "".join(f"- {path}\n" for path in paths)
            + "I have finished my assigned pass. Please verify the repository as a whole."
        )
        blocks.append(ContributorBlock(group=group, paths=paths, text=text))
    return tuple(blocks)


def rotated_blocks(
    blocks: tuple[ContributorBlock, ...], rotation: int
) -> tuple[ContributorBlock, ...]:
    """Three cyclic orderings of one immutable block set."""
    if rotation not in (0, 1, 2):
        raise ValueError("rotation must be 0, 1, or 2")
    return blocks[rotation:] + blocks[:rotation]
