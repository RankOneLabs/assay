"""Contract checks for the pre-run fact-shapes cell plan."""

from dataclasses import FrozenInstanceError, replace
from itertools import product
from pathlib import Path, PurePosixPath
from typing import get_args

import pytest
from code_extension.fact_shapes.cells import (
    CELLS,
    Feature,
    Shape,
    TaskType,
    render_cell_table,
)
from pydantic import TypeAdapter

from assay.models import Identifier

STUDY = Path(__file__).resolve().parents[1] / 'studies/fact-shapes-2026-11'


def test_plan_change() -> None:
    text = (STUDY / 'plan-change.md').read_text()
    for phrase in (
        '57 of 57', '11 of 11', 'intent-only', 'per-fact', 'rename',
        'at most 1 of its 10 non-control manipulated facts', 'before any run',
        'further written plan change before the full run',
    ):
        assert phrase in text


def test_factor_order_and_identifiers() -> None:
    assert get_args(Shape) == (
        'type_enforced', 'reference', 'name_only', 'sibling_only',
        'outside_code', 'existing_state',
    )
    assert get_args(TaskType) == ('additive', 'rename')
    assert get_args(Feature) == ('stage', 'evidence_kind', 'route_permission')
    adapter = TypeAdapter(Identifier)
    for shape in get_args(Shape):
        assert adapter.validate_python(shape) == shape


def test_full_ordered_product() -> None:
    assert len(CELLS) == 36
    assert [(c.feature, c.task_type, c.shape) for c in CELLS] == list(
        product(get_args(Feature), get_args(TaskType), get_args(Shape))
    )


def test_frozen_and_nonempty() -> None:
    with pytest.raises(FrozenInstanceError):
        CELLS[0].directory_hops = 9
    with pytest.raises(ValueError, match='at least one holder'):
        replace(CELLS[0], holders=())


def test_fact_identity() -> None:
    facts = {c.fact_id for c in CELLS}
    anchors = {c.anchor_fact_id for c in CELLS}
    assert len(facts) == 36
    assert len(anchors) == 6
    assert facts.isdisjoint(anchors)
    for feature, task_type in product(get_args(Feature), get_args(TaskType)):
        scenario = [c for c in CELLS if (c.feature, c.task_type) == (feature, task_type)]
        assert len({c.anchor_fact_id for c in scenario}) == 1
    for cell in CELLS:
        assert cell.test_title_prefix == f'fact:{cell.fact_id}: '
        assert cell.fact_statement.startswith(
            'Adding' if cell.task_type == 'additive' else 'Renaming the existing'
        )


def test_kinds_and_import_distances() -> None:
    for cell in CELLS:
        if cell.shape == 'existing_state':
            expected = 'reuse_vs_duplicate' if cell.task_type == 'additive' else 'reader_update'
            assert cell.fact_kind == expected
            assert cell.import_hops != 1
        else:
            assert cell.fact_kind == 'holder_update'
        if cell.shape in ('name_only', 'sibling_only', 'outside_code'):
            assert cell.import_hops is None
        if cell.shape == 'reference':
            assert isinstance(cell.import_hops, int) and cell.import_hops >= 1
        if cell.shape == 'outside_code':
            assert all(p.endswith('.sql') for p in cell.holders)


def test_holder_update_checks_and_migration_plan() -> None:
    for feature, task_type in product(get_args(Feature), get_args(TaskType)):
        statements = {
            c.fact_statement for c in CELLS
            if (c.feature, c.task_type) == (feature, task_type)
            and c.shape in ('type_enforced', 'reference', 'name_only', 'sibling_only')
        }
        assert len(statements) == 4
    migrations = sorted({c.holders[0] for c in CELLS if c.shape == 'outside_code'})
    assert migrations == [
        'evidence_kind/001_constraint.sql',
        'route_permission/001_constraint.sql',
        'stage/001_constraint.sql',
    ]
    rendered = render_cell_table()
    assert 'lexicographic' in rendered
    assert 'no cross-feature ordering dependency' in rendered


def test_paths_and_directory_distances() -> None:
    for cell in CELLS:
        assert cell.holders
        for raw in (cell.edit_site, *cell.holders):
            path = PurePosixPath(raw)
            assert not path.is_absolute()
            assert '..' not in path.parts
            assert '\\' not in raw
            assert str(path) == raw
        edit_parts = PurePosixPath(cell.edit_site).parent.parts
        distances = []
        for holder in cell.holders:
            holder_parts = PurePosixPath(holder).parent.parts
            common = 0
            for left, right in zip(edit_parts, holder_parts, strict=False):
                if left != right:
                    break
                common += 1
            distances.append(len(edit_parts) + len(holder_parts) - 2 * common)
        assert min(distances) == cell.directory_hops
    for feature, task_type in product(get_args(Feature), get_args(TaskType)):
        assert len({
            c.directory_hops for c in CELLS if (c.feature, c.task_type) == (feature, task_type)
        }) == 1


def test_rendered_document() -> None:
    rendered = render_cell_table()
    assert (STUDY / 'cell-table.md').read_bytes() == rendered.encode('utf-8')
    rows = [line for line in rendered.splitlines() if line.startswith('| ')][2:]
    assert len(rows) == 36
    assert sum('| reader_update |' in row for row in rows) == 3
    assert sum('| reuse_vs_duplicate |' in row for row in rows) == 3
    for cell, row in zip(CELLS, rows, strict=True):
        columns = row.split('|')
        assert columns[10].strip() == (
            'none' if cell.import_hops is None else str(cell.import_hops)
        )
