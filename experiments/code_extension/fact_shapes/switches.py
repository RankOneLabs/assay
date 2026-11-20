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
    'stage': 'stageHeadings',
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


# Round 5: stage holders are implicit. Every version declares per-stage traits next to
# the type; a holder reads its trait, except in its own version, where it encodes the
# stages another way (a position, numeric codes, or display text) and names none.
STAGE_HEADINGS: dict[str, str] = {
    'queued': 'Waiting', 'active': 'In progress', 'complete': 'Done', 'triaged': 'Awaiting triage',
}
# The new stage's traits, as the stage-additive task states them.
TRIAGED_TRAITS = (
    '  triaged: { heading: "Awaiting triage", open: true, code: 4, retentionDays: 30, '
    'route: "/jobs/triage", next: ["queued", "complete"] },'
)
_POSITIONAL: dict[Shape, tuple[str, str, str]] = {
    'reference': ('stage/policy.ts', 'openForChanges', 'types'),
    'name_only': ('src/domain/escalation_validation.ts', 'escalates', 'stageTypes'),
    'sibling_only': ('src/services/bulk_moves.ts', 'movableInBulk', 'stageTypes'),
    'existing_state': ('src/services/export_snapshots.ts', 'exportedLive', 'stageTypes'),
}
_RETENTION_MIGRATION = 'db/migrations/008_retention_periods.sql'
_RETENTION_UNTYPED = 'export const retentionSchema = retentionFields;'
_RETENTION_TRAIT = (
    'export const retentionSchema = retentionFields.refine(value => value.days <= '
    'stageTypes.stageTraits[value.stage].retentionDays, "retention exceeds the stage limit");'
)
_RETENTION_CHECK = (
    '  days INTEGER NOT NULL CONSTRAINT retention_days CHECK (days BETWEEN 1 AND 3650),'
)


def _retention_codes(extra: str = '') -> str:
    return (
        '  days INTEGER NOT NULL CONSTRAINT retention_days CHECK (days BETWEEN 1 AND '
        f'(CASE stage_code WHEN 3 THEN 3650{extra} ELSE 365 END)),'
    )


def _headings(values: tuple[str, ...]) -> str:
    entries = ', '.join(f'{value}: {json.dumps(STAGE_HEADINGS[value])}' for value in values)
    return f'export const stageHeadings: Record<stageTypes.Stage, string> = {{ {entries} }};'


def holder_switches(cell: Cell) -> tuple[tuple[str, str, str], ...]:
    """(path, derived text, this version's own text) for each holder file of the cell."""
    feature, shape = cell.feature, cell.shape
    if feature != 'stage':
        return ((
            cell.holders[0], derived_line(feature, shape),
            holder_line(feature, shape, VOCABULARIES[feature]),
        ),)
    if shape == 'type_enforced':
        return ((
            cell.holders[0],
            'export const stageHeadings: Record<stageTypes.Stage, string> = '
            'headings(stageTypes.stageTraits);',
            _headings(VOCABULARIES[feature]),
        ),)
    if shape == 'outside_code':
        return (
            (_RETENTION_MIGRATION, _RETENTION_CHECK, _retention_codes()),
            ('src/domain/validation.ts', _RETENTION_TRAIT, _RETENTION_UNTYPED),
        )
    path, name, namespace = _POSITIONAL[shape]
    head = f'const {name} = (stage: {namespace}.Stage): boolean => {namespace}.'
    return ((path, head + 'stageTraits[stage].open;', head + 'values.indexOf(stage) < 2;'),)


def holder_fixes(cell: Cell) -> tuple[tuple[str, str, str], ...]:
    """(path, this version's text, reference text): the holder update a solution makes."""
    feature, shape = cell.feature, cell.shape
    switches = holder_switches(cell)
    if feature != 'stage':
        (path, _derived, own), = switches
        return ((path, own, holder_line(feature, shape, target_values(cell))),)
    if shape == 'type_enforced':
        (path, _derived, own), = switches
        return ((path, own, _headings(target_values(cell))),)
    if shape == 'outside_code':
        if cell.task_type == 'additive':
            fixed = _retention_codes(' WHEN 4 THEN 30')
            return ((_RETENTION_MIGRATION, _retention_codes(), fixed),)
        # A rename keeps the stage's code; restoring the typed limit is the update.
        return (('src/domain/validation.ts', _RETENTION_UNTYPED, _RETENTION_TRAIT),)
    # Positional holders: the update reads the declared trait.
    return tuple((path, own, derived) for path, derived, own in switches)


def anchor_edits(cell: Cell) -> tuple[Replacement, ...]:
    return (Replacement(f'{cell.feature}/anchor.ts', ANCHOR_OLD, ANCHOR_LINE),)


def _edits(cell: Cell) -> tuple[Replacement, ...]:
    holders = tuple(Replacement(path, derived, own) for path, derived, own in holder_switches(cell))
    return (*holders, *anchor_edits(cell))


SWITCHES: dict[FactId, tuple[Replacement, ...]] = {cell.fact_id: _edits(cell) for cell in CELLS}


def fact_lines(cell: Cell) -> dict[str, tuple[str, ...]]:
    """Per holder file, the line that is this version's own: what a model must see."""
    lines: dict[str, tuple[str, ...]] = {}
    for path, _derived, own in holder_switches(cell):
        lines[path] = (own,)
    return lines


# A scenario's feature work, identical in every arm and never touching a holder.
# Stage-additive: imported jobs start in triaged (its traits, declared with the type,
# allow leaving only for the waiting or completed stage). Builds take only queued jobs.
FEATURE_EDITS: dict[tuple[Feature, TaskType], tuple[Replacement, ...]] = {
    ('stage', 'additive'): (
        Replacement(
            'src/repositories/jobs.ts',
            '  transition(id: string, stage: Stage, revision: number, now: number): Job {\n',
            '  /** Place a job that is still at its first revision in its starting stage. */\n'
            '  startIn(id: string, stage: Stage): Job {\n'
            '    if (this.require(id).revision !== 1) conflict("job has already changed");\n'
            '    this.db.query("UPDATE jobs SET stage = ? WHERE id = ? AND revision = 1")'
            '.run(stage, id);\n'
            '    return this.require(id);\n'
            '  }\n\n'
            '  transition(id: string, stage: Stage, revision: number, now: number): Job {\n',
        ),
        Replacement(
            'src/services/imports.ts',
            '        for (const item of entry.evidence) '
            'this.evidence.attach(actor, job.id, item);\n'
            '        created.push(job);',
            '        for (const item of entry.evidence) '
            'this.evidence.attach(actor, job.id, item);\n'
            '        // Imported jobs wait for triage once their evidence is attached.\n'
            '        created.push(this.jobRepository.startIn(job.id, "triaged"));',
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
    for path, own, fixed in holder_fixes(cell):
        _replace_once(tree, path, own, fixed)
    if cell.task_type == 'additive':
        _replace_once(
            tree, f'{feature}/types.ts',
            f'{_literals(VOCABULARIES[feature])} as const',
            f'{_literals(target_values(cell))} as const',
        )
        if feature == 'stage':
            _replace_once(tree, 'stage/types.ts', '\n};\n', f'\n{TRIAGED_TRAITS}\n}};\n')
    else:
        old, new = VALUES[feature]
        for path, source in tree.items():
            if path.endswith('.ts') and not path.startswith('tests/'):
                tree[path] = source.replace(json.dumps(old), json.dumps(new))
        if feature == 'stage':
            _replace_once(tree, 'stage/types.ts', f'\n  {old}: {{', f'\n  {new}: {{')
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
