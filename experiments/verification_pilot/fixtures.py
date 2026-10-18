"""Derive the pilot geometry from the pinned raw repository slice."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from verification_pilot.inputs import RENAMES, RenameInput

RAW_REPO = Path(__file__).resolve().parent / "raw" / "repo"
OwnershipGroup = Literal["group_a", "group_b", "group_c"]
GROUPS: tuple[OwnershipGroup, ...] = ("group_a", "group_b", "group_c")


def whole_word_pattern(symbol: str) -> re.Pattern[str]:
    """Match a symbol only at identifier boundaries, including TypeScript '$'."""
    return re.compile(r"(?<![\w$])" + re.escape(symbol) + r"(?![\w$])")


def read_raw_repository(root: Path = RAW_REPO) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*")) if path.is_file() and path != root / "README.md"
    }


def use_sites_for(repository: Mapping[str, str], symbol: str) -> tuple[str, ...]:
    pattern = whole_word_pattern(symbol)
    return tuple(sorted(path for path, source in repository.items() if pattern.search(source)))


@dataclass(frozen=True, slots=True)
class Migration:
    name: str
    old_symbol: str
    new_symbol: str
    defining_module: str
    use_sites: tuple[str, ...]
    kind: Literal["type"] = "type"

    @property
    def ownership_groups(self) -> dict[str, OwnershipGroup]:
        # Sorting and round-robin assignment make the three shares deterministic.
        return {path: GROUPS[index % len(GROUPS)]
                for index, path in enumerate(self.use_sites)}

    def ownership_group_for(self, path: str) -> OwnershipGroup:
        if path in self.ownership_groups:
            return self.ownership_groups[path]
        raise ValueError(f"{self.name}: path is outside the derived use sites: {path}")


def derive_migration(repository: Mapping[str, str], rename: RenameInput) -> Migration:
    sites = use_sites_for(repository, rename.old_symbol)
    if rename.defining_module not in sites:
        raise ValueError(f"{rename.name}: defining module does not contain old symbol")
    if any(rename.new_symbol in source for source in repository.values()):
        raise ValueError(f"{rename.name}: new symbol already appears in the raw slice")
    if len(sites) < 7:
        raise ValueError(f"{rename.name}: fewer than seven use-site files")
    migration = Migration(rename.name, rename.old_symbol, rename.new_symbol,
                          rename.defining_module, sites)
    counts = Counter(migration.ownership_groups.values())
    if any(counts[group] < 2 for group in GROUPS):
        raise ValueError(f"{rename.name}: each owner needs at least two files")
    return migration


def derive_migrations(repository: Mapping[str, str]) -> tuple[Migration, ...]:
    return tuple(derive_migration(repository, rename) for rename in RENAMES)


MIGRATIONS: tuple[Migration, ...] = derive_migrations(read_raw_repository())


@dataclass(frozen=True, slots=True)
class BaseSubject:
    id: str
    migration: Migration
    owner: OwnershipGroup | None
    location: str | None


@dataclass(frozen=True, slots=True)
class PilotSession:
    id: str
    subject_id: str
    arm_id: Literal["t1-native", "t1-quoted"]


def base_subjects(migrations: tuple[Migration, ...] = MIGRATIONS) -> tuple[BaseSubject, ...]:
    """Three planted owners and a clean control for each of four renames."""
    subjects: list[BaseSubject] = []
    for migration in migrations:
        for owner in GROUPS:
            path = next(path for path, group in migration.ownership_groups.items()
                        if group == owner and path != migration.defining_module)
            subjects.append(BaseSubject(f"{migration.name}-{owner}", migration, owner, path))
        subjects.append(BaseSubject(f"{migration.name}-clean", migration, None, None))
    return tuple(subjects)


def pilot_sessions(subjects: tuple[BaseSubject, ...] | None = None) -> tuple[PilotSession, ...]:
    """Pair each planted owner with both T1 handoff presentations."""
    subjects = base_subjects() if subjects is None else subjects
    return tuple(PilotSession(f"{subject.id}-{arm_id}", subject.id, arm_id)
                 for subject in subjects if subject.owner is not None
                 for arm_id in ("t1-native", "t1-quoted"))
