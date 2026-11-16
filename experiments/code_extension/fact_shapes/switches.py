"""Build independently observable fact omissions; legacy service vocabulary stays fixed."""

import json
from pathlib import Path

from code_extension.fact_shapes.cells import CELLS, Cell, FactId, Feature
from code_extension.slice import Replacement

VOCABULARIES: dict[Feature, tuple[str, ...]] = {
    "stage": ("queued", "active", "complete"),
    "evidence_kind": ("document", "image", "testimony"),
    "route_permission": ("case_read", "case_write", "case_admin"),
}
NEW_VALUES = {
    "stage": "triaged",
    "evidence_kind": "attestation",
    "route_permission": "case_inspect",
}
ANCHOR_OLD = '  if (!/^[a-zA-Z0-9_-]{1,80}$/.test(key)) throw new Error("invalid key");'
ANCHOR_LINE = '  if (!/^[a-zA-Z0-9_-]{1,79}$/.test(key)) throw new Error("invalid key");'
BASE = Path(__file__).parent / "base"


def anchor_edits(cell: Cell) -> tuple[Replacement, ...]:
    return (Replacement(f"{cell.feature}/anchor.ts", ANCHOR_OLD, ANCHOR_LINE),)


def supported_values(cell: Cell, *, complete: bool) -> tuple[str, ...]:
    old = VOCABULARIES[cell.feature][0]
    if not complete:
        return (old,)
    new = NEW_VALUES[cell.feature]
    return (old, new) if cell.task_type == "additive" else (new,)


def support_line(cell: Cell, shape: str, *, complete: bool) -> str:
    values = supported_values(cell, complete=complete)
    if shape == "type_enforced":
        entries = ", ".join(f"{json.dumps(value)}: true" for value in values)
        return (
            "export const featureTypes: Record<RequiredFeature, true> & "
            f"Record<string, true> = {{{entries}}};"
        )
    return f"const featureValues: readonly string[] = {json.dumps(list(values))};"


def sql_line(cell: Cell, *, complete: bool) -> str:
    entries = ", ".join(f"'{value}'" for value in supported_values(cell, complete=complete))
    return f"  value TEXT NOT NULL UNIQUE CHECK (value IN ({entries}))"


def owner_line(cell: Cell) -> str:
    return (
        sql_line(cell, complete=False)
        if cell.shape == "outside_code"
        else support_line(cell, cell.shape, complete=False)
    )


def _edits(cell: Cell) -> tuple[Replacement, ...]:
    feature = cell.feature
    edits: list[Replacement] = []
    for shape, filename in (
        ("type_enforced", "types.ts"),
        ("reference", "policy.ts"),
        ("name_only", "names.ts"),
        ("sibling_only", "sibling.ts"),
        ("existing_state", "state.ts"),
    ):
        path = f"{feature}/{filename}"
        old = (BASE / path).read_text()
        line = support_line(cell, shape, complete=shape != cell.shape)
        if shape == "type_enforced":
            extension = (
                'import type { RequiredFeature } from "./edit.ts";\n' + line + "\n"
                "export function supportsFeature(value: string): boolean { "
                "return Object.hasOwn(featureTypes, value); }\n"
            )
        elif shape == "existing_state":
            if feature == "stage":
                method = (
                    "  supportsFeature(value: string, key: string): boolean { "
                    "return featureValues.includes(value) && this.isBuildRunning(key); }\n"
                )
            else:
                method = (
                    "  supportsFeature(value: string, key: string): boolean { "
                    "return featureValues.includes(value) && this.get(key) === value; }\n"
                )
            last = old.rfind("}")
            extension = line + "\n"
            old_with_method = old[:last] + method + old[last:]
            edits.append(Replacement(path, old, extension + old_with_method))
            continue
        else:
            extension = (
                line + "\nexport function supportsFeature(value: string): boolean { "
                "return featureValues.includes(value); }\n"
            )
        edits.append(Replacement(path, old, old + extension))
    path = f"{feature}/001_constraint.sql"
    old = (BASE / path).read_text()
    capability_schema = (
        f"CREATE TABLE {feature}_capabilities (\n"
        "  id TEXT PRIMARY KEY,\n"
        + sql_line(cell, complete=cell.shape != "outside_code")
        + "\n);\n"
    )
    edits.append(Replacement(path, old, old + capability_schema))
    path = f"{feature}/edit.ts"
    old = (BASE / path).read_text()
    type_name = {
        "stage": "Stage",
        "evidence_kind": "EvidenceKind",
        "route_permission": "RoutePermission",
    }[feature]
    new = "export type RequiredFeature = never;\n" + old
    new += (
        "export function requestFeature(key: string, value: RequiredFeature, count = 1): "
        f"{{ key: string; value: {type_name} | RequiredFeature }} {{\n"
        "  return edit(key, value as never, count);\n}\n"
    )
    edits.append(Replacement(path, old, new))
    return (*edits, *anchor_edits(cell))


SWITCHES: dict[FactId, tuple[Replacement, ...]] = {cell.fact_id: _edits(cell) for cell in CELLS}


def fact_lines(cell: Cell) -> tuple[str, ...]:
    if cell.shape == "existing_state":
        source = next(edit.new for edit in SWITCHES[cell.fact_id] if edit.path == cell.holders[0])
        return tuple(
            line
            for line in source.splitlines()
            if line == owner_line(cell) or "private readonly" in line or "supportsFeature(" in line
        )
    return (owner_line(cell),)
