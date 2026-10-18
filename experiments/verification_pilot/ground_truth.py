"""Operator-held locations for generated subject remnants and decoys."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from verification_pilot.fixture import PilotFixture, subject_repository
from verification_pilot.fixtures import BaseSubject, OwnershipGroup, base_subjects

RemnantKind = Literal["stale_type_reference"]
DecoyKind = Literal["historical_changelog", "historical_migration_note", "masking_test"]


@dataclass(frozen=True, slots=True)
class Location:
    migration: str
    path: str
    line: int
    symbol: str
    ownership_group: OwnershipGroup | None


@dataclass(frozen=True, slots=True)
class Remnant:
    kind: RemnantKind
    location: Location


@dataclass(frozen=True, slots=True)
class Decoy:
    kind: DecoyKind
    location: Location


@dataclass(frozen=True, slots=True)
class GroundTruth:
    remnants: tuple[Remnant, ...]
    decoys: tuple[Decoy, ...]


def subject_truth(subject: BaseSubject, fixture: PilotFixture) -> GroundTruth:
    repository = subject_repository(subject, fixture)
    migration = subject.migration
    remnants: tuple[Remnant, ...] = ()
    if subject.location is not None:
        before = fixture.renamed[migration.name][subject.location].splitlines()
        after = repository[subject.location].splitlines()
        lines = [index for index, (left, right) in enumerate(zip(before, after, strict=True), 1)
                 if left != right]
        if len(lines) != 1:
            raise ValueError(f"{subject.id}: expected one changed line")
        remnants = (Remnant("stale_type_reference", Location(
            migration.name, subject.location, lines[0], migration.old_symbol, subject.owner,
        )),)
    decoys = (
        Decoy("historical_changelog", Location(
            migration.name, "CHANGELOG.md", 3, migration.old_symbol, None,
        )),
        Decoy("historical_migration_note", Location(
            migration.name, "docs/migration.md", 3, migration.old_symbol, None,
        )),
    )
    return GroundTruth(remnants, decoys)


def build_specimens(fixture: PilotFixture) -> tuple[dict[str, dict[str, str]], GroundTruth]:
    """Return the derived workspaces and combined operator-held locations."""
    subjects = base_subjects()
    repositories = {subject.id: subject_repository(subject, fixture) for subject in subjects}
    truths = [subject_truth(subject, fixture) for subject in subjects]
    return repositories, GroundTruth(
        tuple(remnant for truth in truths for remnant in truth.remnants),
        tuple(decoy for truth in truths for decoy in truth.decoys),
    )
