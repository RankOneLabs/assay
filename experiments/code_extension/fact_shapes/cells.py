"""Single typed cell source for fact-shapes-2026-11.

Paths are POSIX paths relative to experiments/code_extension/fact_shapes/base/.
Directory hops count steps up from the edit-site directory to the deepest common
ancestor and down to the holder directory (zero for files sharing a directory).
Import hops count edges on the shortest directed import path from edit site to
holder; None means no path. For multiple holders, each distance is the minimum.

Every arm declares the value list in <feature>/types.ts, and the edit site uses
it. The manipulated holder keeps its own independent copy of the list, read only
by its own behavior; in every other arm that holder derives from the type.
Holders sit where a service keeps them, in shared files whose names do not name a
feature: only the type, the edit site and the direct-import policy are in the
feature folder.

The outside_code holder is always a SQLite CHECK constraint in a migration under
db/migrations/. Stored records reference the constrained lookup table (evidence and
grants; for stages, the per-stage retention settings rather than jobs), so a stale
CHECK makes storing such a record with the new value fail. Hidden tests store
and read back such a record through the service, whose in-memory bun:sqlite
database applies every migration there in filename order. Both a new migration
and an edit to the base migration pass.

Stages (round 6) differ: their holders are not copies of the value list but places
that assume work only moves forward, in a nest of runs over jobs over attempts whose
derived state is declared in src/rollup/ and kept by one engine. Their edit site is
the roll-up declarations file, the stage outside_code holder is a trigger in the runs
migration, and only the reference piece and the control's table are imported by the
edit site.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NewType, get_args

Feature = Literal['stage', 'evidence_kind', 'route_permission']
Shape = Literal[
    'type_enforced', 'reference', 'name_only', 'sibling_only', 'outside_code', 'existing_state'
]
TaskType = Literal['additive', 'rename']
FactKind = Literal['holder_update', 'reuse_vs_duplicate', 'reader_update']
FactId = NewType('FactId', str)
RepositoryPath = NewType('RepositoryPath', str)


@dataclass(frozen=True)
class FactHolder:
    """Pre-task evidence for one fact, indexed by base-relative holder path."""

    fact_id: FactId
    holder_paths: tuple[RepositoryPath, ...]
    fact_lines: dict[RepositoryPath, tuple[str, ...]]

    def __post_init__(self) -> None:
        if not self.holder_paths or set(self.fact_lines) != set(self.holder_paths):
            raise ValueError('fact lines must cover exactly the nonempty holder paths')
        for lines in self.fact_lines.values():
            if not lines or any(not line.strip() or '\n' in line for line in lines):
                raise ValueError('fact lines must be nonempty individual source lines')


@dataclass(frozen=True)
class HolderSpec:
    """One entry in holders.json; shared with fact scoring consumers."""

    scenario: str
    shape: Shape
    manipulated: FactHolder
    anchor: FactHolder

    def __post_init__(self) -> None:
        if set(self.manipulated.holder_paths) & set(self.anchor.holder_paths):
            raise ValueError('anchor and manipulated holders must be disjoint')


@dataclass(frozen=True)
class Cell:
    """One planned arm; holders always contains at least one base-relative path."""

    feature: Feature
    shape: Shape
    task_type: TaskType
    edit_site: RepositoryPath
    holders: tuple[RepositoryPath, ...]
    fact_id: FactId
    fact_statement: str
    anchor_fact_id: FactId
    test_title_prefix: str
    import_hops: int | None
    directory_hops: int
    fact_kind: FactKind

    def __post_init__(self) -> None:
        if not self.holders:
            raise ValueError('A cell requires at least one holder')


# Only the chosen shape's holder keeps an independent copy in that arm. The anchor
# is always in anchor.ts, imported by edit.ts, and has the same test in all arms.
_IMPORT_HOPS: dict[Shape, int | None] = {
    'type_enforced': None,
    'reference': 1,
    'name_only': None,
    'sibling_only': None,
    'outside_code': None,
    'existing_state': None,
}


# Round 6: the stage task asks for roll-up behavior through the declarations, so that
# file is the stage edit site. The reference piece and the control's table are one
# import away from it; every other stage holder has no import path from it.
STAGE_EDIT_SITE = 'src/rollup/declarations.ts'
_STAGE_IMPORT_HOPS: dict[Shape, int | None] = {
    'type_enforced': 1,
    'reference': 1,
    'name_only': None,
    'sibling_only': None,
    'outside_code': None,
    'existing_state': None,
}


# Round 6: stage holders are forward-only assumptions about runs, the top level of a
# nest (run, job, attempt) whose state is declared in src/rollup/ and kept by one engine.
# Each is right for every forward move and wrong once a completed job is re-queued.
_STAGE_HOLDERS: dict[Shape, tuple[str, ...]] = {
    # How each stage counts toward its run: a compiler-checked table.
    'type_enforced': ('src/domain/progress.ts',),
    # A roll-up piece the run status is built from, reached through the engine.
    'reference': ('src/rollup/pieces.ts',),
    # The run finish time, recorded outside the roll-up folder.
    'name_only': ('src/timing/finish_times.ts',),
    # The bulk stage change, beside the single-move path.
    'sibling_only': ('src/services/jobs.ts',),
    # The trigger that keeps the stored run status column.
    'outside_code': ('db/migrations/008_runs.sql',),
    # Stored summaries of finished runs.
    'existing_state': ('src/services/run_summaries.ts',),
}


def holder_paths(feature: Feature, shape: Shape) -> tuple[RepositoryPath, ...]:
    """The files that hold this shape's independent behavior when it is manipulated.

    Except for the direct-import policy, each holder file is shared by the three
    features and its name and directory name none of them.
    """
    if feature == 'stage':
        return tuple(RepositoryPath(path) for path in _STAGE_HOLDERS[shape])
    paths: dict[Shape, str] = {
        'type_enforced': 'src/presentation/labels.ts',
        'reference': f'{feature}/policy.ts',
        'name_only': 'src/validation/registry.ts',
        'sibling_only': 'src/services/peer.ts',
        'outside_code': 'db/migrations/001_lookup_tables.sql',
        'existing_state': 'src/preferences/defaults.ts',
    }
    return (RepositoryPath(paths[shape]),)


def _directory_hops(edit_site: str, holder: str) -> int:
    source, target = Path(edit_site).parent.parts, Path(holder).parent.parts
    common = 0
    for left, right in zip(source, target, strict=False):
        if left != right:
            break
        common += 1
    return len(source) + len(target) - 2 * common

# Concrete values lock down what later fixtures and hidden tests must exercise.
VALUES: dict[Feature, tuple[str, str]] = {
    'stage': ('queued', 'triaged'),
    'evidence_kind': ('document', 'attestation'),
    'route_permission': ('case_read', 'case_inspect'),
}
# The value an additive task adds, where it differs from the rename target (round 6).
ADDED_VALUES: dict[Feature, str] = {'stage': 'in_review'}


def _cell(feature: Feature, task_type: TaskType, shape: Shape) -> Cell:
    old, new = VALUES[feature]
    if task_type == 'additive':
        new = ADDED_VALUES.get(feature, new)
    noun = feature.replace('_', ' ')
    action = (
        f'Adding the {new} {noun}'
        if task_type == 'additive'
        else f'Renaming the existing {old} {noun} to {new}'
    )
    verb = 'adds it to' if task_type == 'additive' else 'renames it in'
    kind: FactKind = 'holder_update'
    stage_rules: dict[Shape, str] = {
        'type_enforced': 'its jobs count as open work, not done, in the compiler-checked '
                         'table of how each stage counts toward its run',
        'reference': 're-queuing a job of a finished run makes the run running again, '
                     'though the roll-up piece its status is built from keeps a reached '
                     'value in this version',
        'name_only': 'a run that finishes again records its new finish time, though '
                     'the finish-time module keeps the first one in this version',
        'sibling_only': 'a bulk re-queue leaves each run\'s counts exact, though the bulk '
                        'stage change adds completions to stored counts in this version',
        'outside_code': 'a re-queue in a finished run sets the stored status column back '
                        'to running, though the migration trigger only marks runs finished '
                        'in this version',
        'existing_state': 'a re-queue in a finished run refreshes its stored summary, '
                          'though the summary reader serves any stored summary in this '
                          'version',
    }
    if feature == 'stage':
        if shape == 'existing_state':
            kind = 'reuse_vs_duplicate' if task_type == 'additive' else 'reader_update'
        statement = f'{action}: {stage_rules[shape]}.'
    elif shape == 'existing_state':
        kind = 'reuse_vs_duplicate' if task_type == 'additive' else 'reader_update'
        reader = 'the saved-default reader\'s list of values that follow the current selection'
        statement = (
            f'{action} {verb} {reader}, so stored state for {new} is read live '
            'rather than from a stored copy.'
        )
    elif shape == 'outside_code':
        statement = (
            f'{action} {verb} the migration CHECK constraint, so the service can store '
            f'records with {new}.'
        )
    elif shape == 'type_enforced':
        statement = (
            f'{action} {verb} the exhaustive display-label map that the compiler '
            'checks against the type.'
        )
    elif shape == 'reference':
        statement = (
            f'{action} {verb} the accepted list of the policy called from the edit site.'
        )
    elif shape == 'name_only':
        statement = (
            f'{action} {verb} the descriptively named registry, so its validation '
            f'accepts {new}.'
        )
    else:
        statement = (
            f'{action} {verb} the adjacent operation\'s accepted list, so it also '
            f'accepts {new}.'
        )
    holders = holder_paths(feature, shape)
    edit_site = STAGE_EDIT_SITE if feature == 'stage' else f'{feature}/edit.ts'
    fact_id = FactId(f'{feature}_{task_type}_{shape}')
    return Cell(
        feature=feature,
        shape=shape,
        task_type=task_type,
        edit_site=RepositoryPath(edit_site),
        holders=holders,
        fact_id=fact_id,
        fact_statement=statement,
        anchor_fact_id=FactId(f'{feature}_{task_type}_anchor'),
        test_title_prefix=f'fact:{fact_id}: ',
        import_hops=(_STAGE_IMPORT_HOPS if feature == 'stage' else _IMPORT_HOPS)[shape],
        directory_hops=min(_directory_hops(edit_site, path) for path in holders),
        fact_kind=kind,
    )


CELLS: tuple[Cell, ...] = tuple(
    _cell(feature, task_type, shape)
    for feature in get_args(Feature)
    for task_type in get_args(TaskType)
    for shape in get_args(Shape)
)


def render_cell_table() -> str:
    """Render the reviewed plan deterministically, including its final newline."""
    header = """# fact-shapes-2026-11 cell table

Rendered from `code_extension/fact_shapes/cells.py`; do not edit by hand.
Regenerate from experiments/ with `uv run python -m code_extension.fact_shapes.cells`.
Paths are relative to `experiments/code_extension/fact_shapes/base/`.
Each feature directory contains edit.ts, types.ts, policy.ts and anchor.ts;
anchor.ts holds the scenario's fixed reference-shape anchor in every arm.

Every arm declares the value list in types.ts and edit.ts uses it. The holder
listed below keeps its own independent copy of the list in that arm only, read
only by its own behavior; in the other arms the same holder derives from the
type. Apart from policy.ts, holder files are shared by the three features and
their names do not name a feature.

The four in-code holder_update shapes have distinct checks: an exhaustive display
label map the compiler checks, the policy called by edit.ts, a descriptively named
registry's validation, and an adjacent operation's acceptance. The name_only
registry is used by a separate validation entry point, with no import path from
edit.ts; its descriptive name is the discovery cue. The sibling_only holder is
found through the adjacent operation's analogous code, rather than a descriptive
registry name. Neither has an import path from edit.ts; reference deliberately has
one import hop.

Directory hops are steps up from the edit-site directory to the deepest common
ancestor and down to the holder directory (0 for a shared directory). Import hops
are the shortest directed import path's edge count; none means no path. For
multiple holders, both distances use the nearest holder (the minimum).
The outside_code holder is a SQLite CHECK constraint in a migration on a lookup
table that business tables reference. Tests store and read back a record with the
new or renamed value through the service, whose fresh in-memory bun:sqlite database
applies all migrations; a new migration and an edit to the base migration both pass.
Apply every `db/migrations/*.sql` migration once to the same database in
lexicographic filename order (001_lookup_tables.sql creates all three lookup
tables; later numbered migrations create the tables of other service features).
Each feature owns an independent table,
with no cross-feature ordering dependency. Follow-up migrations use increasing
numeric filename prefixes in the same directory.

"""
    header = header.rstrip() + "\n\n" + (
        "| feature | task type | shape | edit site | holder file(s) | fact id | required fact "
        "| anchor fact id | hidden test | import hops | directory hops | fact kind |\n"
        + "| --- " * 12 + "|\n"
    )
    rows = []
    for cell in CELLS:
        columns = (
            cell.feature, cell.task_type, cell.shape, cell.edit_site,
            ', '.join(cell.holders), cell.fact_id, cell.fact_statement,
            cell.anchor_fact_id, f'`{cell.test_title_prefix}`',
            'none' if cell.import_hops is None else str(cell.import_hops),
            str(cell.directory_hops), cell.fact_kind,
        )
        rows.append('| ' + ' | '.join(columns) + ' |\n')
    return header + ''.join(rows)


if __name__ == '__main__':
    destination = Path(__file__).resolve().parents[1] / 'studies/fact-shapes-2026-11/cell-table.md'
    destination.write_text(render_cell_table(), encoding='utf-8')
