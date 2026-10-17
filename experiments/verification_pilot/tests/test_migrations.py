"""Section 7.6 checks against the pinned declaration population."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from verification_pilot.fixture import load_fixture
from verification_pilot.migrations import MIGRATIONS, generate_rename, selected_occurrences


def test_four_declared_migrations_have_six_uses_in_six_files() -> None:
    repository = load_fixture().repository
    assert len(MIGRATIONS) == 4
    for migration in MIGRATIONS:
        declaration = repository[migration.defining_module]
        if migration.kind == "type":
            pattern = rf"\bexport\s+type\s+{migration.old_symbol}\b"
        elif migration.kind == "value":
            pattern = rf"\bexport\s+const\s+{migration.old_symbol}\b"
        else:
            pattern = rf"\breadonly\s+{migration.old_symbol}\s*:"
        assert re.search(pattern, declaration), migration.name
        using_files = {
            path
            for path, source in repository.items()
            if path != migration.defining_module and selected_occurrences(source, migration)
        }
        uses = sum(selected_occurrences(repository[path], migration) for path in using_files)
        assert uses >= 6, migration.name
        assert len(using_files) >= 6, migration.name
        assert set(migration.use_sites) == {
            path for path, source in repository.items() if selected_occurrences(source, migration)
        }


def test_part2_anchor_is_not_renamed() -> None:
    assert all(
        "readJsonPointer" not in (migration.old_symbol, migration.new_symbol)
        for migration in MIGRATIONS
    )


def test_directory_ownership_rotates() -> None:
    by_directory: dict[str, dict[str, str]] = {}
    for migration in MIGRATIONS:
        for path, group in migration.ownership_groups.items():
            by_directory.setdefault(str(Path(path).parent), {})[migration.name] = group
    assert all(
        len(set(assignments.values())) > 1
        for assignments in by_directory.values()
        if len(assignments) == len(MIGRATIONS)
    )
    assert all(
        set(migration.ownership_groups) == set(migration.use_sites) for migration in MIGRATIONS
    )


def test_generator_rejects_old_or_new_extra_occurrences() -> None:
    repository = load_fixture().repository
    for migration in MIGRATIONS:
        renamed = generate_rename(repository, migration)
        assert all(not selected_occurrences(source, migration) for source in renamed.values())
        old_use = "ok()" if migration.kind == "value" else f"{migration.old_symbol} "
        extra_old = {**repository, "src/pilot-extra.ts": old_use}
        with pytest.raises(AssertionError, match="use sites differ"):
            generate_rename(extra_old, migration)
        extra_new = dict(repository)
        extra_new["src/pilot-extra.ts"] = migration.new_symbol
        with pytest.raises(AssertionError, match="new symbol already occurs"):
            generate_rename(extra_new, migration)
