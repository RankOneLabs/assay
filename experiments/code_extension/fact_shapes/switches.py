"""Give each arm's holder an independent copy of the value list, by counted literal edits.

Every arm declares the value list in ``<feature>/types.ts`` and the edit site uses it.
In the base every candidate holder derives from that type. An arm rewrites only its
manipulated holder into an explicit literal copy that only the holder's own behavior
reads, so arms differ in that one file.

This module also derives the private patch trees. The reference updates the type,
the arm's holder and the label boundary (a rename also renames every service literal).
An omission is that reference with one fact's file left as it was: missing the holder
still updates the type.
"""

import json
from collections.abc import Mapping

from code_extension.fact_shapes.cells import CELLS, VALUES, Cell, FactId, Feature, Shape
from code_extension.slice import Replacement

VOCABULARIES: dict[Feature, tuple[str, ...]] = {
    'stage': ('queued', 'active', 'complete'),
    'evidence_kind': ('document', 'image', 'testimony'),
    'route_permission': ('case_read', 'case_write', 'case_admin'),
}
TYPE_NAMES: dict[Feature, str] = {
    'stage': 'Stage', 'evidence_kind': 'EvidenceKind', 'route_permission': 'RoutePermission',
}
LABEL_MAPS: dict[Feature, str] = {
    'stage': 'stageLabels',
    'evidence_kind': 'evidenceKindLabels',
    'route_permission': 'routePermissionLabels',
}
_PLURAL: dict[Feature, str] = {
    'stage': 'Stages', 'evidence_kind': 'Kinds', 'route_permission': 'Permissions',
}
ANCHOR_OLD = '  if (!/^[a-zA-Z0-9_-]{1,80}$/.test(key)) throw new Error("invalid key");'
ANCHOR_LINE = (
    '  if (!/^[a-zA-Z0-9_-]+$/.test(key) || key.length > 79) throw new Error("invalid key");'
)
DERIVED_SQL = '  value TEXT NOT NULL UNIQUE CHECK (length(value) > 0)'


def _literals(values: tuple[str, ...]) -> str:
    return '[' + ', '.join(json.dumps(value) for value in values) + ']'


def display_label(value: str) -> str:
    """The base's derived label for a snake_case value, spelled out by the control."""
    return value[:1].upper() + value[1:].replace('_', ' ')


def _list_name(feature: Feature, shape: Shape) -> str:
    plural = _PLURAL[feature]
    if shape == 'existing_state':
        return 'liveStatusStages' if feature == 'stage' else f'currentSelection{plural}'
    prefix = {'reference': 'accepted', 'name_only': 'registered', 'sibling_only': 'peer'}[shape]
    return prefix + plural


def holder_line(feature: Feature, shape: Shape, values: tuple[str, ...]) -> str:
    """The manipulated holder's single explicit declaration of ``values``."""
    if shape == 'outside_code':
        sql = ', '.join(f"'{value}'" for value in values)
        return f'  value TEXT NOT NULL UNIQUE CHECK (value IN ({sql}))'
    if shape == 'type_enforced':
        entries = ', '.join(f'{value}: {json.dumps(display_label(value))}' for value in values)
        return (
            f'export const {LABEL_MAPS[feature]}: Record<{TYPE_NAMES[feature]}, string> = '
            f'{{ {entries} }};'
        )
    return f'const {_list_name(feature, shape)}: readonly string[] = {_literals(values)};'


def derived_line(feature: Feature, shape: Shape) -> str:
    """The same holder's line in the base, where it derives from the type."""
    if shape == 'outside_code':
        return DERIVED_SQL
    if shape == 'type_enforced':
        return (
            f'export const {LABEL_MAPS[feature]}: Record<{TYPE_NAMES[feature]}, string> = '
            'titleLabels(values);'
        )
    return f'const {_list_name(feature, shape)}: readonly string[] = values;'


def _import_edit(cell: Cell) -> Replacement | None:
    """Drop the type's value import that only the derived form used."""
    feature, shape, type_name = cell.feature, cell.shape, TYPE_NAMES[cell.feature]
    path = cell.holders[0]
    if shape == 'outside_code':
        return None
    if shape == 'type_enforced':
        return Replacement(
            path,
            f'import {{ values, type {type_name} }} from "../../{feature}/types.ts";\n'
            'import { titleLabels } from "./labels.ts";\n',
            f'import type {{ {type_name} }} from "../../{feature}/types.ts";\n',
        )
    if shape == 'reference':
        return Replacement(
            path,
            f'import {{ values, type {type_name} }} from "./types.ts";\n',
            f'import type {{ {type_name} }} from "./types.ts";\n',
        )
    if shape == 'existing_state' and feature != 'stage':
        return Replacement(
            path,
            f'import {{ values, type {type_name} }} from "../../{feature}/types.ts";\n',
            f'import type {{ {type_name} }} from "../../{feature}/types.ts";\n',
        )
    return Replacement(path, f'import {{ values }} from "../../{feature}/types.ts";\n', '')


def anchor_edits(cell: Cell) -> tuple[Replacement, ...]:
    return (Replacement(f'{cell.feature}/anchor.ts', ANCHOR_OLD, ANCHOR_LINE),)


def _edits(cell: Cell) -> tuple[Replacement, ...]:
    imports = _import_edit(cell)
    holder = Replacement(
        cell.holders[0],
        derived_line(cell.feature, cell.shape),
        holder_line(cell.feature, cell.shape, VOCABULARIES[cell.feature]),
    )
    return (*((imports,) if imports else ()), holder, *anchor_edits(cell))


SWITCHES: dict[FactId, tuple[Replacement, ...]] = {cell.fact_id: _edits(cell) for cell in CELLS}


def fact_lines(cell: Cell) -> tuple[str, ...]:
    """The holder's independent declaration is the evidence for an additive or rename edit."""
    return (holder_line(cell.feature, cell.shape, VOCABULARIES[cell.feature]),)


def target_values(cell: Cell) -> tuple[str, ...]:
    """The value list after the task: one value added, or the first value renamed."""
    old, new = VALUES[cell.feature]
    base = VOCABULARIES[cell.feature]
    if cell.task_type == 'additive':
        return (*base, new)
    return tuple(new if value == old else value for value in base)


def _replace_once(tree: dict[str, str], path: str, old: str, new: str) -> None:
    actual = tree[path].count(old)
    if actual != 1:
        raise ValueError(f'{path}: expected 1 match of {old!r}, actual {actual}')
    tree[path] = tree[path].replace(old, new)


def reference_tree(cell: Cell, arm: Mapping[str, str]) -> dict[str, str]:
    """A complete solution in this arm: type, holder, service literals and anchor."""
    tree = dict(arm)
    feature = cell.feature
    _replace_once(
        tree, cell.holders[0],
        holder_line(feature, cell.shape, VOCABULARIES[feature]),
        holder_line(feature, cell.shape, target_values(cell)),
    )
    if cell.task_type == 'additive':
        _replace_once(
            tree, f'{feature}/types.ts',
            f'{_literals(VOCABULARIES[feature])} as const',
            f'{_literals(target_values(cell))} as const',
        )
    else:
        old, new = VALUES[feature]
        for path, source in tree.items():
            if path.endswith('.ts') and not path.startswith('tests/'):
                tree[path] = source.replace(json.dumps(old), json.dumps(new))
    _replace_once(tree, f'{feature}/anchor.ts', ANCHOR_LINE, ANCHOR_OLD)
    return tree


def omission_tree(
    cell: Cell, arm: Mapping[str, str], reference: Mapping[str, str], dropped: FactId,
) -> dict[str, str]:
    """The reference with only the dropped fact's file left as the arm has it."""
    paths = cell.holders if dropped == cell.fact_id else (f'{cell.feature}/anchor.ts',)
    if dropped not in (cell.fact_id, cell.anchor_fact_id):
        raise ValueError(f'{dropped}: not a fact of {cell.fact_id}')
    tree = dict(reference)
    for path in paths:
        tree[path] = arm[path]
    return tree
