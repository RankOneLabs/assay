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
    ADDED_VALUES,
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


# Round 6: stage holders assume work only moves forward. Runs roll up their jobs through
# declared pieces and one engine; each version has one place that is right for every
# forward move and wrong once a completed job goes back to the queue. That place is the
# version's own text below; every other version has the derived text.
_PROGRESS_PATH = 'src/domain/progress.ts'
_PROGRESS_HEAD = (
    'export const stageProgress: Record<stageTypes.Stage, stageTypes.Progress> = '
)
_PROGRESS: dict[str, str] = {
    'queued': 'open', 'active': 'open', 'complete': 'done', 'in_review': 'open',
    'triaged': 'open',
}
PROGRESS_TYPE = 'Record<stageTypes.Stage, stageTypes.Progress>'
_BULK_REFRESH = (
    '      const affected = new Set<string>();\n'
    '      const moved = parsed.changes.map(change => {\n'
    '        const job = this.move(actor, change.id, change.transition, peer);\n'
    '        if (job.runId !== null) affected.add(job.runId);\n'
    '        return job;\n'
    '      });\n'
    '      for (const runId of affected) this.rollups.refresh("run", runId);'
)
_ADDER = (
    '      const affected = new Map<string, Job[]>();\n'
    '      const moved = parsed.changes.map(change => {\n'
    '        const job = this.move(actor, change.id, change.transition, peer);\n'
    '        if (job.runId !== null) '
    'affected.set(job.runId, [...affected.get(job.runId) ?? [], job]);\n'
    '        return job;\n'
    '      });\n'
    '      for (const [runId, jobs] of affected) {\n'
    '        const run = this.runs.require(runId);\n'
    '        const added = jobs.filter(job => job.finishedAt !== null).length;\n'
    '        const done = run.state.done + added;\n'
    '        const status = done === run.state.total ? "finished" : "running";\n'
    '        this.runs.store(runId, { ...run.state, open: run.state.open - added, done, status }, '
    'this.now());\n'
    '      }'
)
RUN_TRIGGER_BODY = (
    "BEGIN\n"
    "  UPDATE runs SET status = json_extract(NEW.state, '$.status') WHERE id = NEW.id;"
)
_FORWARD_TRIGGER_BODY = (
    "WHEN json_extract(NEW.state, '$.total') > 0 "
    "AND json_extract(NEW.state, '$.done') = json_extract(NEW.state, '$.total')\n"
    "BEGIN\n"
    "  UPDATE runs SET status = 'finished' WHERE id = NEW.id;"
)
_STAGE_SWITCHES: dict[Shape, tuple[str, str, str]] = {
    'type_enforced': (
        _PROGRESS_PATH, _PROGRESS_HEAD + 'progressByStage(stageTypes.stageTraits);', '',
    ),
    'reference': (
        'src/rollup/pieces.ts',
        '  children => (condition(children) ? yes : no);',
        '  (children, previous) => (previous === yes || condition(children) ? yes : no);',
    ),
    'name_only': (
        'src/timing/finish_times.ts',
        '  return finished ? recorded ?? now : null;',
        '  return recorded ?? (finished ? now : null);',
    ),
    'sibling_only': ('src/services/jobs.ts', _BULK_REFRESH, _ADDER),
    'outside_code': ('db/migrations/008_runs.sql', RUN_TRIGGER_BODY, _FORWARD_TRIGGER_BODY),
    'existing_state': (
        'src/services/run_summaries.ts',
        '    if (saved !== null && saved.revision === run.revision) return saved.summary;',
        '    if (saved !== null) return saved.summary;',
    ),
}
# The new stage's traits as the stage-additive reference declares them, and the
# completed stage now leads back to the queue.
IN_REVIEW_TRAITS = (
    '  in_review: { heading: "In review", open: true, progress: "open", route: "/jobs/review", '
    'next: ["complete", "active"] },'
)
_COMPLETE_TRAITS = (
    '  complete: { heading: "Done", open: false, progress: "done", route: "/jobs/archive", '
    'next: [] },'
)


def stage_progress(values: tuple[str, ...]) -> str:
    """The compiler-checked table of how each stage counts toward its run."""
    entries = ', '.join(f'{value}: {json.dumps(_PROGRESS[value])}' for value in values)
    return f'{_PROGRESS_HEAD}{{ {entries} }};'


def holder_switches(cell: Cell) -> tuple[tuple[str, str, str], ...]:
    """(path, derived text, this version's own text) for each holder file of the cell."""
    feature, shape = cell.feature, cell.shape
    if feature != 'stage':
        return ((
            cell.holders[0], derived_line(feature, shape),
            holder_line(feature, shape, VOCABULARIES[feature]),
        ),)
    path, derived, own = _STAGE_SWITCHES[shape]
    if shape == 'type_enforced':
        own = stage_progress(VOCABULARIES[feature])
    return ((path, derived, own),)


def holder_fixes(cell: Cell) -> tuple[tuple[str, str, str], ...]:
    """(path, this version's text, reference text): the holder update a solution makes."""
    feature, shape = cell.feature, cell.shape
    (path, derived, own), = holder_switches(cell)
    if feature != 'stage':
        return ((path, own, holder_line(feature, shape, target_values(cell))),)
    if shape == 'type_enforced':
        return ((path, own, stage_progress(target_values(cell))),)
    # Every other stage holder goes back to the derived text: through the engine.
    return ((path, own, derived),)


def anchor_edits(cell: Cell) -> tuple[Replacement, ...]:
    return (Replacement(f'{cell.feature}/anchor.ts', ANCHOR_OLD, ANCHOR_LINE),)


def _edits(cell: Cell) -> tuple[Replacement, ...]:
    holders = tuple(Replacement(path, derived, own) for path, derived, own in holder_switches(cell))
    return (*holders, *anchor_edits(cell))


SWITCHES: dict[FactId, tuple[Replacement, ...]] = {cell.fact_id: _edits(cell) for cell in CELLS}


def fact_lines(cell: Cell) -> dict[str, tuple[str, ...]]:
    """Per holder file, the lines that are this version's own: what a model must see."""
    lines: dict[str, tuple[str, ...]] = {}
    for path, derived, own in holder_switches(cell):
        base = set(derived.splitlines())
        lines[path] = tuple(
            line for line in own.splitlines()
            if any(char.isalnum() for char in line) and line not in base
        )
    return lines


# A scenario's feature work, identical in every arm and never touching a holder.
# Stage-additive: a passing build of a job in a run waits for review; jobs outside a run
# still complete directly. The stage's traits are declared with the type (see
# reference_tree), so review moves are ordinary stage changes, single or in bulk.
FEATURE_EDITS: dict[tuple[Feature, TaskType], tuple[Replacement, ...]] = {
    ('stage', 'additive'): (
        Replacement(
            'src/services/builds.ts',
            '      const stage = parsed.exitCode === 0 ? "complete" : "queued";\n',
            '      // A passing build of a job in a run waits for review before it completes.\n'
            '      const stage = parsed.exitCode !== 0 ? "queued" '
            ': job.runId === null ? "complete" : "in_review";\n',
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
        return (*base, ADDED_VALUES.get(cell.feature, new))
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
            _replace_once(
                tree, 'stage/types.ts', _COMPLETE_TRAITS + '\n',
                _COMPLETE_TRAITS.replace('next: []', 'next: ["queued"]') + '\n'
                + IN_REVIEW_TRAITS + '\n',
            )
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
