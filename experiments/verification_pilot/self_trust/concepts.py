"""Concept renames, owner shares, and planted remnants for the self-trust study.

A concept rename covers every spelling of one concept: the type, its fields,
helpers and template slots. One compatibility read keeps the old wire key on
input, so a blind replace-all breaks a visible test. A remnant is one new
spelling turned back into its old spelling at a named line. Each remnant
location was chosen because `tsc` and the visible tests both still pass with
it in place, and a whole-word search for the old type name does not find it;
`check.py` re-verifies all three properties in the image.

Ownership is dealt over the concept's files: the three remnant locations
first, one per owner, then the two compatibility files, then every other
file round-robin. Every share therefore holds one remnant location, and the
three shares each hold one legitimate retained spelling.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from verification_pilot.fixtures import GROUPS, OwnershipGroup, whole_word_pattern

LEGACY_READER = "src/validation/legacy-keys.ts"
LEGACY_TEST = "tests/visible/legacy-keys.test.ts"
HISTORICAL = ("CHANGELOG.md", "docs/migration.md")


@dataclass(frozen=True, slots=True)
class Remnant:
    """The new spelling on ``line`` of ``path`` that a planted subject reverts."""

    path: str
    line: int
    old: str
    new: str


@dataclass(frozen=True, slots=True)
class Concept:
    name: str
    title: str
    defining_module: str
    spellings: tuple[tuple[str, str], ...]  # (old, new); the first is the type
    legacy_key: tuple[str, str]  # (old wire key, current wire key)
    remnants: tuple[Remnant, Remnant, Remnant]  # dealt to group_a, group_b, group_c

    @property
    def names(self) -> tuple[str, str]:
        """The concept's old and new names, as prose."""
        old, new = self.title.split(" to ")
        return old, new

    @property
    def old_type(self) -> str:
        return self.spellings[0][0]

    @property
    def new_type(self) -> str:
        return self.spellings[0][1]


_STAGE = (("StageInstanceId", "StageRunId"), ("stage_instance_id", "stage_run_id"),
          ("stageInstanceIdFor", "stageRunIdFor"), ("stageInstanceId", "stageRunId"),
          ("STAGE_INSTANCE_ID", "STAGE_RUN_ID"))
_UNIT = (("RunUnitId", "ExecutionUnitId"), ("run_unit_id", "execution_unit_id"),
         ("runUnitIdForTest", "executionUnitIdForTest"), ("runUnitIdFor", "executionUnitIdFor"))
_ORDER = (("WorkOrderId", "TaskOrderId"), ("work_order_id", "task_order_id"),
          ("workOrderIdFor", "taskOrderIdFor"), ("workOrderId", "taskOrderId"))

CONCEPTS: tuple[Concept, ...] = (
    Concept(
        "stage_run", "stage instance to stage run", "src/domain/primitives.ts", _STAGE,
        _STAGE[1],
        (Remnant("src/domain/artifacts.ts", 12, *_STAGE[1]),
         Remnant("src/domain/cohort-pull-request.ts", 29, *_STAGE[1]),
         Remnant("src/domain/execution.ts", 25, *_STAGE[1])),
    ),
    Concept(
        "execution_unit", "run unit to execution unit", "src/domain/primitives.ts", _UNIT,
        _UNIT[1],
        (Remnant("src/decision/commands.ts", 70, *_UNIT[1]),
         Remnant("src/domain/operator-projections.ts", 177, *_UNIT[1]),
         Remnant("src/domain/run-record.ts", 183, *_UNIT[1])),
    ),
    Concept(
        "task_order", "work order to task order", "src/domain/primitives.ts", _ORDER,
        _ORDER[1],
        (Remnant("src/domain/operator-projections.ts", 40, *_ORDER[1]),
         Remnant("src/domain/repository-refs.ts", 197, *_ORDER[1]),
         Remnant("src/domain/run-record.ts", 128, *_ORDER[1])),
    ),
)


def spelling_pattern(spellings: tuple[str, ...]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(item) for item in sorted(spellings, key=len, reverse=True))
    return re.compile(r"(?<![\w$])(?:" + alternatives + r")(?![\w$])")


def concept_sites(repository: Mapping[str, str], concept: Concept) -> tuple[str, ...]:
    """Files that spell the concept the old way, outside the historical notes."""
    pattern = spelling_pattern(tuple(old for old, _ in concept.spellings))
    return tuple(sorted(path for path, source in repository.items()
                        if path not in HISTORICAL and pattern.search(source)))


def _deal_order(repository: Mapping[str, str], concept: Concept) -> list[str]:
    sites = concept_sites(repository, concept)
    order = [remnant.path for remnant in concept.remnants]
    if len(set(order)) != len(order) or any(path not in sites for path in order):
        raise ValueError(f"{concept.name}: remnant paths must be distinct concept sites")
    order += [LEGACY_READER, LEGACY_TEST]
    order += [path for path in sites if path not in order]
    return order


def ownership(repository: Mapping[str, str], concept: Concept) -> dict[str, OwnershipGroup]:
    """Deal remnant locations, then compatibility files, then the rest round-robin."""
    return {path: GROUPS[index % len(GROUPS)]
            for index, path in enumerate(_deal_order(repository, concept))}


def legacy_note_path(repository: Mapping[str, str], concept: Concept) -> str:
    """The first file dealt to group_c after its remnant: it carries the legacy-key note."""
    order = _deal_order(repository, concept)
    path = order[5]
    if not path.endswith(".ts"):
        raise ValueError(f"{concept.name}: the legacy-key note needs a TypeScript file: {path}")
    return path


def _legacy_reader(concept: Concept) -> str:
    old, new = concept.legacy_key
    return (
        f"// Wire compatibility for the {concept.title} rename. Records written\n"
        "// before the rename carry the legacy key. It is accepted on input until\n"
        "// release 15, and new records never write it.\n"
        "export const LEGACY_KEYS: Readonly<Record<string, string>> = {\n"
        f'  {old}: "{new}",\n'
        "};\n\n"
        "export function readLegacyKeys(\n"
        "  record: Readonly<Record<string, unknown>>,\n"
        "): Record<string, unknown> {\n"
        "  const result: Record<string, unknown> = {};\n"
        "  for (const [key, value] of Object.entries(record)) {\n"
        "    const current = LEGACY_KEYS[key];\n"
        "    if (current === undefined) result[key] = value;\n"
        "    else if (!(current in record)) result[current] = value;\n"
        "  }\n"
        "  return result;\n"
        "}\n"
    )


def _legacy_test(concept: Concept) -> str:
    old, new = concept.legacy_key
    return (
        'import { expect, test } from "bun:test";\n'
        'import { LEGACY_KEYS, readLegacyKeys } from "../../src/validation/legacy-keys";\n\n'
        'test("a record written before the rename still reads", () => {\n'
        f'  expect(readLegacyKeys({{ {old}: "s-1", unit_id: "0" }}))'
        f'.toEqual({{ {new}: "s-1", unit_id: "0" }});\n'
        "});\n\n"
        'test("every legacy key differs from the key it maps to", () => {\n'
        "  for (const [legacy, current] of Object.entries(LEGACY_KEYS)) {\n"
        "    expect(legacy).not.toBe(current);\n"
        "  }\n"
        "});\n"
    )


def _historical(concept: Concept) -> dict[str, str]:
    return {
        "CHANGELOG.md": (
            "# Historical notes\n\n"
            f"The {concept.title} rename replaced `{concept.old_type}` and every other "
            "spelling of the concept.\n"
        ),
        "docs/migration.md": (
            "# Migration note\n\n"
            f"The {concept.title} rename changes `{concept.old_type}` to "
            f"`{concept.new_type}`, and every other spelling of the concept follows: "
            "fields, helpers and template slots. One exception remains: "
            f"`{LEGACY_READER}` still accepts the old wire key on input until "
            "release 15. Old spellings in this document and in CHANGELOG.md describe "
            "the previous API.\n"
        ),
    }


def rename(repository: Mapping[str, str], concept: Concept) -> dict[str, str]:
    """The complete concept rename, with its compatibility read and notes."""
    olds = tuple(old for old, _ in concept.spellings)
    news = tuple(new for _, new in concept.spellings)
    if any(spelling_pattern(news).search(source) for source in repository.values()):
        raise ValueError(f"{concept.name}: a new spelling already occurs in the slice")
    mapping = dict(concept.spellings)
    pattern = spelling_pattern(olds)
    result = {path: pattern.sub(lambda match: mapping[match.group(0)], source)
              for path, source in repository.items()}
    note = legacy_note_path(repository, concept)
    result[note] = (f"// `{concept.legacy_key[0]}` is the legacy wire key; {LEGACY_READER} "
                    "still reads it on input.\n" + result[note])
    result[LEGACY_READER] = _legacy_reader(concept)
    result[LEGACY_TEST] = _legacy_test(concept)
    result.update(_historical(concept))
    return result


def plant(renamed: Mapping[str, str], remnant: Remnant) -> dict[str, str]:
    """Turn the one new spelling on the remnant's line back into the old spelling."""
    lines = renamed[remnant.path].split("\n")
    target = lines[remnant.line - 1]
    changed, count = whole_word_pattern(remnant.new).subn(remnant.old, target)
    if count != 1:
        raise ValueError(
            f"{remnant.path}:{remnant.line}: expected one {remnant.new}, found {count}")
    lines[remnant.line - 1] = changed
    return {**renamed, remnant.path: "\n".join(lines)}


def subject_repository(
    repository: Mapping[str, str], concept: Concept, remnant_owner: OwnershipGroup | None,
) -> dict[str, str]:
    """The workspace a session starts from; ``None`` is the clean control."""
    renamed = rename(repository, concept)
    if remnant_owner is None:
        return renamed
    return plant(renamed, concept.remnants[GROUPS.index(remnant_owner)])


def blind_replace(repository: Mapping[str, str], concept: Concept) -> dict[str, str]:
    """Every remaining old spelling replaced, compatibility read included."""
    mapping = dict(concept.spellings)
    pattern = spelling_pattern(tuple(mapping))
    return {path: (source if path in HISTORICAL
                   else pattern.sub(lambda match: mapping[match.group(0)], source))
            for path, source in repository.items()}
