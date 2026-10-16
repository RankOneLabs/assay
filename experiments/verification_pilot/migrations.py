"""Four pinned rename declarations and an exhaustively checked rename generator."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

MigrationKind = Literal["type", "value", "object_key"]
OwnershipGroup = Literal["group_a", "group_b", "group_c", "group_d"]
GROUPS: tuple[OwnershipGroup, ...] = ("group_a", "group_b", "group_c", "group_d")


@dataclass(frozen=True, slots=True)
class Migration:
    name: str
    old_symbol: str
    new_symbol: str
    kind: MigrationKind
    defining_module: str
    use_sites: tuple[str, ...]
    rotation: int

    def ownership_group_for(self, path: str) -> OwnershipGroup:
        """Return the rotated group for a path in a participating directory."""
        directory = path.rsplit("/", 1)[0]
        directories = sorted({site.rsplit("/", 1)[0] for site in self.use_sites})
        if directory not in directories:
            raise ValueError(f"{self.name}: unassigned directory {directory}")
        return GROUPS[(directories.index(directory) + self.rotation) % len(GROUPS)]

    @property
    def ownership_groups(self) -> dict[str, OwnershipGroup]:
        """Assign each touched file, rotating directory ownership per migration."""
        return {path: self.ownership_group_for(path) for path in self.use_sites}


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        name="json_value",
        old_symbol="JsonValue",
        new_symbol="PilotJsonValue",
        kind="type",
        defining_module="src/domain/primitives.ts",
        rotation=0,
        use_sites=(
            "src/compiler/compile-workflow.ts",
            "src/compiler/context-requirements.ts",
            "src/compiler/resolve-execution.ts",
            "src/decision/commands.ts",
            "src/decision/derive.ts",
            "src/decision/snapshot.ts",
            "src/domain/artifacts.ts",
            "src/domain/cohort-pull-request.ts",
            "src/domain/compiled-workflow.ts",
            "src/domain/delegated-session.ts",
            "src/domain/execution.ts",
            "src/domain/json-pointer.ts",
            "src/domain/operator-projections.ts",
            "src/domain/primitives.ts",
            "src/domain/repository-refs.ts",
            "src/domain/run-context.ts",
            "src/domain/run-event.ts",
            "src/domain/run-record.ts",
            "src/domain/runs.ts",
            "src/domain/workflow.ts",
            "tests/visible/decision/snapshot-builder.ts",
            "tests/visible/dev-flow-stage-contracts.test.ts",
        ),
    ),
    Migration(
        name="stage_instance_id",
        old_symbol="StageInstanceId",
        new_symbol="PilotStageInstanceId",
        kind="type",
        defining_module="src/domain/primitives.ts",
        rotation=1,
        use_sites=(
            "src/compiler/resolve-execution.ts",
            "src/decision/commands.ts",
            "src/decision/derive.ts",
            "src/decision/ids.ts",
            "src/decision/snapshot.ts",
            "src/domain/artifacts.ts",
            "src/domain/cohort-pull-request.ts",
            "src/domain/execution.ts",
            "src/domain/gates.ts",
            "src/domain/operator-projections.ts",
            "src/domain/primitives.ts",
            "src/domain/run-event.ts",
            "src/domain/run-record.ts",
            "src/domain/runs.ts",
            "src/domain/session-hold.ts",
            "src/domain/wait.ts",
            "src/domain/workflow.ts",
            "tests/visible/decision/snapshot-builder.ts",
            "tests/visible/dev-flow-stage-contracts.test.ts",
            "tests/visible/resolve-execution.test.ts",
        ),
    ),
    Migration(
        name="result_ok",
        old_symbol="ok",
        new_symbol="pilotOk",
        kind="value",
        defining_module="src/domain/primitives.ts",
        rotation=2,
        use_sites=(
            "src/compiler/compile-workflow.ts",
            "src/compiler/resolve-execution.ts",
            "src/decision/derive.ts",
            "src/domain/final-pull-request.ts",
            "src/domain/primitives.ts",
            "src/domain/repository-provisioning.ts",
            "src/domain/repository-refs.ts",
            "src/validation/workflow-definition.ts",
            "tests/visible/compile-workflow.test.ts",
        ),
    ),
    Migration(
        name="slot_bindings_key",
        old_symbol="slot_bindings",
        new_symbol="pilot_slot_bindings",
        kind="object_key",
        defining_module="src/domain/delegated-session.ts",
        rotation=3,
        use_sites=(
            "src/compiler/resolve-execution.ts",
            "src/domain/delegated-session.ts",
            "src/seed/dev-flow-v14.ts",
            "src/validation/delegated-session.ts",
            "tests/visible/context-requirements.test.ts",
            "tests/visible/delegated-session-validation.test.ts",
            "tests/visible/resolve-execution.test.ts",
            "tests/visible/workflow-definition.test.ts",
            "workflow-config/definitions/dev_flow_v11.json",
            "workflow-config/definitions/dev_flow_v14.json",
        ),
    ),
)


def symbol_pattern(migration: Migration) -> re.Pattern[str]:
    return re.compile(r"(?<![\w$])" + re.escape(migration.old_symbol) + r"(?![\w$])")


def _value_replacements(source: str, old: str, new: str) -> tuple[str, int]:
    """Rename the callable and its imports, leaving Result.ok discriminants alone."""
    count = 0

    def replace_import(match: re.Match[str]) -> str:
        nonlocal count
        before, members, after = match.groups()
        changed, n = re.subn(r"\bok\b", new, members)
        count += n
        return before + changed + after

    source = re.sub(
        r'(import\s*\{)([^}]*)(\}\s*from\s*["\'][^"\']*primitives["\'])',
        replace_import,
        source,
    )
    source, n = re.subn(r"(?<=export const )ok(?=\s*=)", new, source)
    count += n
    source, n = re.subn(r"(?<![\w$.])ok(?=\s*(?:<[^>\n]+>)?\s*\()", new, source)
    count += n
    return source, count


def selected_occurrences(source: str, migration: Migration) -> int:
    if migration.kind == "value":
        _, count = _value_replacements(source, migration.old_symbol, migration.new_symbol)
        return count
    return len(symbol_pattern(migration).findall(source))


def generate_rename(repository: Mapping[str, str], migration: Migration) -> dict[str, str]:
    """Rename all declared sites and reject extra or missing old/new occurrences."""
    if migration.old_symbol == "readJsonPointer" or migration.new_symbol == "readJsonPointer":
        raise ValueError("Part 2 anchor readJsonPointer is reserved")
    expected = set(migration.use_sites)
    actual = {
        path for path, source in repository.items() if selected_occurrences(source, migration)
    }
    if actual != expected:
        raise AssertionError(f"{migration.name}: use sites differ: {actual ^ expected}")
    new_pattern = re.compile(r"(?<![\w$])" + re.escape(migration.new_symbol) + r"(?![\w$])")
    if any(new_pattern.search(source) for source in repository.values()):
        raise AssertionError(f"{migration.name}: new symbol already occurs")
    renamed = dict(repository)
    for path in migration.use_sites:
        source = repository[path]
        if migration.kind == "value":
            changed, count = _value_replacements(source, migration.old_symbol, migration.new_symbol)
        else:
            changed, count = symbol_pattern(migration).subn(migration.new_symbol, source)
        if not count or len(new_pattern.findall(changed)) != count:
            raise AssertionError(f"{migration.name}: unintended new occurrence in {path}")
        if selected_occurrences(changed, migration):
            raise AssertionError(f"{migration.name}: old symbol remains in {path}")
        renamed[path] = changed
    if {path for path, source in renamed.items() if selected_occurrences(source, migration)}:
        raise AssertionError(f"{migration.name}: unintended old occurrence remains")
    return renamed
