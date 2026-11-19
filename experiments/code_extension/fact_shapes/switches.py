"""Give each arm's holder an independent copy of the value list, by counted literal edits.

Every arm declares the value list in ``<feature>/types.ts`` and the edit site uses it.
In the base every candidate holder derives from that type. An arm rewrites only its
manipulated holder into an explicit literal copy that only the holder's own behavior
reads, so arms differ in that one file.

This module also derives the private patch trees. The reference implements the
task's feature (shared by every arm of a scenario), and updates the type, the arm's
holder and the label boundary (a rename also renames every service literal). An
omission is that reference with one fact's file left as it was: missing the holder
still updates the type and keeps the feature.
"""

import json
from collections.abc import Mapping

from code_extension.fact_shapes.cells import (
    CELLS,
    VALUES,
    Cell,
    FactId,
    Feature,
    Shape,
    TaskType,
)
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
# Shared holder files import each feature's types as a namespace, so a holder's
# literal copy still uses that import (through its types) and the switch is one line.
NAMESPACES: dict[Feature, str] = {
    'stage': 'stageTypes', 'evidence_kind': 'kindTypes', 'route_permission': 'permissionTypes',
}


def _literals(values: tuple[str, ...]) -> str:
    return '[' + ', '.join(json.dumps(value) for value in values) + ']'


def display_label(value: str) -> str:
    """The base's derived label for a snake_case value, spelled out by the control."""
    return value[:1].upper() + value[1:].replace('_', ' ')


def _list_name(feature: Feature, shape: Shape) -> str:
    plural = _PLURAL[feature]
    if shape == 'existing_state':
        return 'liveExportStages' if feature == 'stage' else f'currentSelection{plural}'
    prefix = {'reference': 'accepted', 'name_only': 'registered', 'sibling_only': 'peer'}[shape]
    return prefix + plural


def label_type(feature: Feature) -> str:
    """The label map's key type, spelled through the shared file's namespace import."""
    return f'{NAMESPACES[feature]}.{TYPE_NAMES[feature]}'


def holder_line(feature: Feature, shape: Shape, values: tuple[str, ...]) -> str:
    """The manipulated holder's single explicit declaration of ``values``."""
    if shape == 'outside_code':
        sql = ', '.join(f"'{value}'" for value in values)
        return (
            f'  value TEXT NOT NULL UNIQUE CONSTRAINT {feature}_value_check '
            f'CHECK (value IN ({sql}))'
        )
    if shape == 'type_enforced':
        entries = ', '.join(f'{value}: {json.dumps(display_label(value))}' for value in values)
        return (
            f'export const {LABEL_MAPS[feature]}: Record<{label_type(feature)}, string> = '
            f'{{ {entries} }};'
        )
    return f'const {_list_name(feature, shape)}: readonly string[] = {_literals(values)};'


def derived_line(feature: Feature, shape: Shape) -> str:
    """The same holder's line in the base, where it derives from the type."""
    if shape == 'outside_code':
        return (
            f'  value TEXT NOT NULL UNIQUE CONSTRAINT {feature}_value_check '
            'CHECK (length(value) > 0)'
        )
    namespace = 'types' if shape == 'reference' else NAMESPACES[feature]
    if shape == 'type_enforced':
        return (
            f'export const {LABEL_MAPS[feature]}: Record<{label_type(feature)}, string> = '
            f'titleLabels({namespace}.values);'
        )
    return f'const {_list_name(feature, shape)}: readonly string[] = {namespace}.values;'


def anchor_edits(cell: Cell) -> tuple[Replacement, ...]:
    return (Replacement(f'{cell.feature}/anchor.ts', ANCHOR_OLD, ANCHOR_LINE),)


def _edits(cell: Cell) -> tuple[Replacement, ...]:
    holder = Replacement(
        cell.holders[0],
        derived_line(cell.feature, cell.shape),
        holder_line(cell.feature, cell.shape, VOCABULARIES[cell.feature]),
    )
    return (holder, *anchor_edits(cell))


SWITCHES: dict[FactId, tuple[Replacement, ...]] = {cell.fact_id: _edits(cell) for cell in CELLS}


def fact_lines(cell: Cell) -> tuple[str, ...]:
    """The holder's independent declaration is the evidence for an additive or rename edit."""
    return (holder_line(cell.feature, cell.shape, VOCABULARIES[cell.feature]),)


# A scenario's feature work, identical in every arm and never touching a holder.
# Stage-additive: imported jobs start in triaged, which may only be left for the
# initial waiting stage or the completed stage. Builds already take only queued jobs.
FEATURE_EDITS: dict[tuple[Feature, TaskType], tuple[Replacement, ...]] = {
    ('stage', 'additive'): (
        Replacement(
            'src/services/jobs.ts',
            'import { enforceLimit } from "../../stage/policy.ts";\n',
            'import { enforceLimit } from "../../stage/policy.ts";\n'
            'import type { Stage } from "../../stage/types.ts";\n',
        ),
        Replacement(
            'src/services/jobs.ts',
            '  create(actor: Principal, input: unknown): Job {',
            '  create(actor: Principal, input: unknown, stage: Stage = "queued"): Job {',
        ),
        Replacement(
            'src/services/jobs.ts',
            '      const job = this.jobs.create(parsed, "queued", now);',
            '      const job = this.jobs.create(parsed, stage, now);',
        ),
        Replacement(
            'src/services/imports.ts',
            '        const job = this.jobs.create(actor, entry.job);',
            '        const job = this.jobs.create(actor, entry.job, "triaged");',
        ),
        Replacement(
            'src/domain/transitions.ts',
            'export function canTransition(from: Stage, to: Stage): boolean {\n',
            'export function canTransition(from: Stage, to: Stage): boolean {\n'
            '  if (from === "triaged") return to === "queued" || to === "complete";\n',
        ),
    ),
}


def feature_edits(cell: Cell) -> tuple[Replacement, ...]:
    return FEATURE_EDITS.get((cell.feature, cell.task_type), ())


def target_values(cell: Cell) -> tuple[str, ...]:
    """The value list after the task: one value added, or the first value renamed."""
    old, new = VALUES[cell.feature]
    base = VOCABULARIES[cell.feature]
    if cell.task_type == 'additive':
        return (*base, new)
    return tuple(new if value == old else value for value in base)


def _replace_once(
    tree: dict[str, str], path: str, old: str, new: str, count: int = 1,
) -> None:
    actual = tree[path].count(old)
    if actual != count:
        raise ValueError(f'{path}: expected {count} match of {old!r}, actual {actual}')
    tree[path] = tree[path].replace(old, new)


def reference_tree(cell: Cell, arm: Mapping[str, str]) -> dict[str, str]:
    """A complete solution in this arm: type, holder, service literals and anchor."""
    tree = dict(arm)
    feature = cell.feature
    for edit in feature_edits(cell):
        if edit.path in cell.holders:
            raise ValueError(f'{cell.fact_id}: feature edit touches the holder {edit.path}')
        _replace_once(tree, edit.path, edit.old, edit.new, edit.count)
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
