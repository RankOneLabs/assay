"""Exact remnant and decoy locations in the generated pilot specimens."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from verification_pilot.fixture import PilotFixture
from verification_pilot.migrations import MIGRATIONS, OwnershipGroup

RemnantKind = Literal["stale_type_reference", "stale_type_import", "fallback_object_key"]
DecoyKind = Literal["result_discriminant", "comment", "masking_test"]


@dataclass(frozen=True, slots=True)
class Location:
    migration: str
    path: str
    line: int
    symbol: str
    ownership_group: OwnershipGroup


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
    remnants: tuple[Remnant, Remnant, Remnant]
    decoys: tuple[Decoy, Decoy, Decoy]


MASKING_TEST_PATH = "tests/visible/pilot-mask.test.ts"
MASKING_TEST = """import { expect, test } from "bun:test";
import { bindingCount } from "../../src/domain/pilot-slot-fallback";

test("slot binding key is present", () => {
  // This test passes because the fallback still accepts an old key.
  const unmigrated = JSON.parse('{"slot_bindings":{"A":"x"}}');
  expect(bindingCount(unmigrated)).toBe(1);
});
"""
FALLBACK_PATH = "src/domain/pilot-slot-fallback.ts"
FALLBACK_SOURCE = """export const bindingCount = (
  config: { pilot_slot_bindings?: Record<string, unknown> },
): number => {
  const legacy = (config as Record<string, Record<string, unknown> | undefined>)["slot_bindings"];
  return Object.keys(config.pilot_slot_bindings ?? legacy ?? {}).length;
};
"""


def _line(source: str, needle: str) -> int:
    lines = [index for index, text in enumerate(source.splitlines(), 1) if needle in text]
    if len(lines) != 1:
        raise AssertionError(f"expected one location for {needle!r}; found {lines}")
    return lines[0]


def build_specimens(fixture: PilotFixture) -> tuple[dict[str, dict[str, str]], GroundTruth]:
    """Inject three distinct incomplete-migration remnants and three decoys."""
    trees = {name: dict(repository) for name, repository in fixture.renamed.items()}
    by_name = {migration.name: migration for migration in MIGRATIONS}
    truth: list[Remnant] = []

    reference = by_name["json_value"]
    reference_path = "src/domain/run-context.ts"
    source = trees[reference.name][reference_path]
    # One use remains old while its import was renamed.
    line_index = next(
        i
        for i, line in enumerate(source.splitlines())
        if "PilotJsonValue" in line and "import" not in line
    )
    lines = source.splitlines(keepends=True)
    lines[line_index] = lines[line_index].replace("PilotJsonValue", "JsonValue", 1)
    trees[reference.name][reference_path] = "".join(lines)
    truth.append(
        Remnant(
            "stale_type_reference",
            Location(
                reference.name,
                reference_path,
                line_index + 1,
                reference.old_symbol,
                reference.ownership_groups[reference_path],
            ),
        )
    )

    imported = by_name["stage_instance_id"]
    import_path = "src/domain/gates.ts"
    source = trees[imported.name][import_path]
    lines = source.splitlines(keepends=True)
    line_index = next(
        i for i, line in enumerate(lines) if "import" in line and "PilotStageInstanceId" in line
    )
    lines[line_index] = lines[line_index].replace("PilotStageInstanceId", "StageInstanceId", 1)
    trees[imported.name][import_path] = "".join(lines)
    truth.append(
        Remnant(
            "stale_type_import",
            Location(
                imported.name,
                import_path,
                line_index + 1,
                imported.old_symbol,
                imported.ownership_groups[import_path],
            ),
        )
    )

    key = by_name["slot_bindings_key"]
    trees[key.name][FALLBACK_PATH] = FALLBACK_SOURCE
    truth.append(
        Remnant(
            "fallback_object_key",
            Location(
                key.name,
                FALLBACK_PATH,
                _line(FALLBACK_SOURCE, '["slot_bindings"]'),
                key.old_symbol,
                key.ownership_group_for(FALLBACK_PATH),
            ),
        )
    )

    value = by_name["result_ok"]
    discriminant_path = "src/domain/primitives.ts"
    discriminant_line = next(
        i
        for i, text in enumerate(trees[value.name][discriminant_path].splitlines(), 1)
        if "readonly ok: true" in text
    )
    note_path = "src/domain/pilot-note.ts"
    trees[imported.name][note_path] = (
        "// StageInstanceId is a historical spelling in this comment.\nexport {};\n"
    )
    trees[key.name][MASKING_TEST_PATH] = MASKING_TEST
    decoys = (
        Decoy(
            "result_discriminant",
            Location(
                value.name,
                discriminant_path,
                discriminant_line,
                "ok",
                value.ownership_groups[discriminant_path],
            ),
        ),
        Decoy(
            "comment",
            Location(
                imported.name,
                note_path,
                1,
                imported.old_symbol,
                imported.ownership_group_for(note_path),
            ),
        ),
        Decoy(
            "masking_test",
            Location(
                key.name,
                MASKING_TEST_PATH,
                _line(MASKING_TEST, 'JSON.parse(\'{"slot_bindings"'),
                key.old_symbol,
                key.ownership_group_for(MASKING_TEST_PATH),
            ),
        ),
    )
    return trees, GroundTruth((truth[0], truth[1], truth[2]), decoys)
