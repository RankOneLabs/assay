"""Single typed cell source for fact-shapes-2026-11.

Paths are POSIX paths relative to experiments/code_extension/fact_shapes/base/.
Directory hops count steps up from the edit-site directory to the deepest common
ancestor and down to the holder directory (zero for files sharing a directory).
Import hops count edges on the shortest directed import path from edit site to
holder; None means no path. For multiple holders, each distance is the minimum.

Every arm declares the value list in <feature>/types.ts, and the edit site uses
it. The manipulated holder keeps its own independent copy of the list, read only
by its own behavior; in every other arm that holder derives from the type.
Holders sit where a service keeps them: only the type, the edit site and the
direct-import policy are in the feature folder.

The outside_code holder is always a SQLite CHECK constraint in a migration under
db/migrations/. Hidden tests apply all migrations there to a fresh in-memory
bun:sqlite database in filename order and insert the new or renamed value. Both a
new migration and an edit to the base migration pass.
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
_MIGRATION_NUMBER: dict[Feature, int] = {'stage': 1, 'evidence_kind': 2, 'route_permission': 3}
_PLURAL: dict[Feature, str] = {
    'stage': 'stages', 'evidence_kind': 'evidence_kinds', 'route_permission': 'route_permissions',
}
_IMPORT_HOPS: dict[Shape, int | None] = {
    'type_enforced': None,
    'reference': 1,
    'name_only': None,
    'sibling_only': None,
    'outside_code': None,
    'existing_state': None,
}


def holder_path(feature: Feature, shape: Shape) -> RepositoryPath:
    """The one file that holds this shape's independent copy when it is manipulated."""
    paths: dict[Shape, str] = {
        'type_enforced': f'src/presentation/{feature}_labels.ts',
        'reference': f'{feature}/policy.ts',
        'name_only': f'src/validation/registered_{_PLURAL[feature]}.ts',
        'sibling_only': f'src/services/{feature}_peer.ts',
        'outside_code': f'db/migrations/{_MIGRATION_NUMBER[feature]:03d}_{feature}_values.sql',
        'existing_state': (
            'src/sessions/build_status.ts' if feature == 'stage'
            else f'src/preferences/{feature}_defaults.ts'
        ),
    }
    return RepositoryPath(paths[shape])


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


def _cell(feature: Feature, task_type: TaskType, shape: Shape) -> Cell:
    old, new = VALUES[feature]
    noun = feature.replace('_', ' ')
    action = (
        f'Adding the {new} {noun}'
        if task_type == 'additive'
        else f'Renaming the existing {old} {noun} to {new}'
    )
    verb = 'adds it to' if task_type == 'additive' else 'renames it in'
    kind: FactKind = 'holder_update'
    if shape == 'existing_state':
        kind = 'reuse_vs_duplicate' if task_type == 'additive' else 'reader_update'
        reader = (
            'the build-status reader\'s list of stages that follow the live session'
            if feature == 'stage'
            else 'the saved-default reader\'s list of values that follow the current selection'
        )
        statement = (
            f'{action} {verb} {reader}, so stored state for {new} is read live '
            'rather than from a stored copy.'
        )
    elif shape == 'outside_code':
        statement = (
            f'{action} {verb} the migration CHECK constraint, so inserting {new} '
            'succeeds after applying all migrations.'
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
    holder = holder_path(feature, shape)
    fact_id = FactId(f'{feature}_{task_type}_{shape}')
    return Cell(
        feature=feature,
        shape=shape,
        task_type=task_type,
        edit_site=RepositoryPath(f'{feature}/edit.ts'),
        holders=(holder,),
        fact_id=fact_id,
        fact_statement=statement,
        anchor_fact_id=FactId(f'{feature}_{task_type}_anchor'),
        test_title_prefix=f'fact:{fact_id}: ',
        import_hops=_IMPORT_HOPS[shape],
        directory_hops=_directory_hops(f'{feature}/edit.ts', holder),
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
type. Missing the holder leaves every other behavior passing.

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
The outside_code holder is a SQLite CHECK constraint in a migration. Tests apply
all migrations to a fresh in-memory bun:sqlite database and insert the new or
renamed value; a new migration and an edit to the base migration both pass.
Apply every `db/migrations/*.sql` migration once to the same database in
lexicographic filename order (initially 001_stage_values.sql,
002_evidence_kind_values.sql, then 003_route_permission_values.sql). Each feature
owns an independent table with no cross-feature ordering dependency. Follow-up
migrations use increasing numeric filename prefixes in the same directory.

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
