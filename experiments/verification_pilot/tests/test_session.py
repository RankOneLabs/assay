"""A migration has one block set; rotations only permute it."""

from __future__ import annotations

from verification_pilot.migrations import GROUPS, MIGRATIONS
from verification_pilot.session import contributor_blocks, rotated_blocks


def test_block_set_is_derived_from_ownership() -> None:
    for migration in MIGRATIONS:
        blocks = contributor_blocks(migration)
        assert tuple(block.group for block in blocks) == GROUPS
        assert {path for block in blocks for path in block.paths} == set(migration.use_sites)
        assert sum(len(block.paths) for block in blocks) == len(migration.use_sites)
        for block in blocks:
            assert all(migration.ownership_group_for(path) == block.group for path in block.paths)


def test_three_rotations_only_change_order() -> None:
    for migration in MIGRATIONS:
        blocks = contributor_blocks(migration)
        rotations = [rotated_blocks(blocks, index) for index in range(3)]
        assert rotations == [blocks[index:] + blocks[:index] for index in range(3)]
        assert len({tuple(block.group for block in rotation) for rotation in rotations}) == 3
        for rotation in rotations:
            assert {id(block) for block in rotation} == {id(block) for block in blocks}
