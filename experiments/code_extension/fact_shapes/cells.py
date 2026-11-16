"""Single typed cell source for fact-shapes-2026-11.

Paths are POSIX paths relative to experiments/code_extension/fact_shapes/base/.
Directory hops count steps up from the edit-site directory to the deepest common
ancestor and down to the holder directory (zero for files sharing a directory).
Import hops count edges on the shortest directed import path from edit site to
holder; None means no path. For multiple holders, each distance is the minimum.

The outside_code holder is always a SQLite CHECK constraint plus the migration
that sets it. Hidden tests apply all migrations to a fresh in-memory bun:sqlite
database and insert the new or renamed value. Both a new migration and an edit
to the base migration pass.
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


# Each feature has edit.ts and its six candidate holders as siblings. Only the
# chosen shape's holder carries the manipulated fact in that arm. The anchor is
# always in anchor.ts, imported by edit.ts, and has the same test in all six arms.
_HOLDERS: dict[Shape, tuple[str, int | None]] = {
    'type_enforced': ('types.ts', 1),
    'reference': ('policy.ts', 1),
    'name_only': ('names.ts', 1),
    'sibling_only': ('sibling.ts', None),
    'outside_code': ('001_constraint.sql', None),
    'existing_state': ('state.ts', None),
}
# Concrete values lock down what later fixtures and hidden tests must exercise.
_VALUES: dict[Feature, tuple[str, str]] = {
    'stage': ('queued', 'triaged'),
    'evidence_kind': ('document', 'attestation'),
    'route_permission': ('case_read', 'case_inspect'),
}


def _cell(feature: Feature, task_type: TaskType, shape: Shape) -> Cell:
    old, new = _VALUES[feature]
    noun = feature.replace('_', ' ')
    action = (
        f'Adding the {new} {noun}'
        if task_type == 'additive'
        else f'Renaming the existing {old} {noun} to {new}'
    )
    kind: FactKind = 'holder_update'
    if shape == 'existing_state':
        if task_type == 'additive':
            kind = 'reuse_vs_duplicate'
            statement = f'{action} reuses the existing stored source without duplicating it.'
        else:
            kind = 'reader_update'
            statement = f'{action} updates every reader to follow the renamed stored source.'
    elif shape == 'outside_code':
        statement = f'{action} permits inserting {new} after applying all migrations.'
    else:
        statement = f'{action} updates the holder so the service accepts {new}.'
    filename, import_hops = _HOLDERS[shape]
    fact_id = FactId(f'{feature}_{task_type}_{shape}')
    return Cell(
        feature=feature,
        shape=shape,
        task_type=task_type,
        edit_site=RepositoryPath(f'{feature}/edit.ts'),
        holders=(RepositoryPath(f'{feature}/{filename}'),),
        fact_id=fact_id,
        fact_statement=statement,
        anchor_fact_id=FactId(f'{feature}_{task_type}_anchor'),
        test_title_prefix=f'fact:{fact_id}: ',
        import_hops=import_hops,
        directory_hops=0,
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
Each feature directory contains edit.ts and the candidate holders listed below;
anchor.ts holds the scenario's fixed reference-shape anchor in every arm.

Directory hops are steps up from the edit-site directory to the deepest common
ancestor and down to the holder directory (0 for a shared directory). Import hops
are the shortest directed import path's edge count; none means no path. For
multiple holders, both distances use the nearest holder (the minimum).
The outside_code holder is a SQLite CHECK constraint plus its migration. Tests
apply all migrations to a fresh in-memory bun:sqlite database and insert the new
or renamed value; a new migration and an edit to the base migration both pass.


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
