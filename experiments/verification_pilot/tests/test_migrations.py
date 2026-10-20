"""Use-site counts and ownership are derived from whole-word matches."""

from __future__ import annotations

import re
from collections import Counter

import pytest

from verification_pilot.fixture import load_fixture
from verification_pilot.fixtures import GROUPS, MIGRATIONS, use_sites_for, whole_word_pattern
from verification_pilot.migrations import generate_rename, selected_occurrences


def test_four_renames_match_pinned_file_counts_and_three_owner_floor() -> None:
    repository = load_fixture().repository
    assert tuple(len(migration.use_sites) for migration in MIGRATIONS) == (20, 18, 10, 8)
    for migration in MIGRATIONS:
        assert re.search(rf"\bexport\s+type\s+{migration.old_symbol}\b",
                         repository[migration.defining_module])
        assert migration.use_sites == use_sites_for(repository, migration.old_symbol)
        assert all(migration.new_symbol not in source for source in repository.values())
        counts = Counter(migration.ownership_groups.values())
        assert all(counts[group] >= 2 for group in GROUPS)
        assert set(migration.ownership_groups) == set(migration.use_sites)


def test_whole_word_matching_excludes_embedded_identifiers() -> None:
    assert whole_word_pattern("RunUnitId").findall("RunUnitId") == ["RunUnitId"]
    assert not whole_word_pattern("RunUnitId").search(
        "LongRunUnitId RunUnitIdExtra $RunUnitId RunUnitId$"
    )
    assert use_sites_for({"embedded.ts": "LongRunUnitId"}, "RunUnitId") == ()


def test_generator_rejects_source_drift_and_renames_every_site() -> None:
    repository = load_fixture().repository
    for migration in MIGRATIONS:
        renamed = generate_rename(repository, migration)
        assert all(not selected_occurrences(source, migration) for source in renamed.values())
        with pytest.raises(AssertionError, match="use sites differ"):
            generate_rename({**repository, "src/extra.ts": migration.old_symbol}, migration)
        with pytest.raises(AssertionError, match="new symbol already occurs"):
            generate_rename({**repository, "src/extra.ts": migration.new_symbol}, migration)
