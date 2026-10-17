"""Whole-word symbol renaming for the derived pilot migrations."""

from __future__ import annotations

import re
from collections.abc import Mapping

from verification_pilot.fixtures import (
    GROUPS as GROUPS,
)
from verification_pilot.fixtures import (
    MIGRATIONS as MIGRATIONS,
)
from verification_pilot.fixtures import Migration as Migration
from verification_pilot.fixtures import (
    OwnershipGroup as OwnershipGroup,
)
from verification_pilot.fixtures import whole_word_pattern


def symbol_pattern(migration: Migration) -> re.Pattern[str]:
    return whole_word_pattern(migration.old_symbol)


def selected_occurrences(source: str, migration: Migration) -> int:
    return len(symbol_pattern(migration).findall(source))


def generate_rename(repository: Mapping[str, str], migration: Migration) -> dict[str, str]:
    """Rename exactly the derived sites and reject source drift."""
    expected = set(migration.use_sites)
    actual = {
        path for path, source in repository.items() if selected_occurrences(source, migration)
    }
    if actual != expected:
        raise AssertionError(f"{migration.name}: use sites differ: {actual ^ expected}")
    new_pattern = whole_word_pattern(migration.new_symbol)
    if any(new_pattern.search(source) for source in repository.values()):
        raise AssertionError(f"{migration.name}: new symbol already occurs")
    result = dict(repository)
    for path in migration.use_sites:
        changed, count = symbol_pattern(migration).subn(migration.new_symbol, repository[path])
        if count == 0:
            raise AssertionError(f"{migration.name}: no old symbol in {path}")
        result[path] = changed
    return result
