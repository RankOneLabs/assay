"""Exact-edit generation rejects drift before changing the supplied base."""

import pytest
from code_extension.fact_shapes.cells import CELLS, FactId
from code_extension.fact_shapes.generate import apply_edits, generate_trees
from code_extension.slice import Replacement


def test_exact_edits_are_sequential_and_pure() -> None:
    base = {'a.ts': 'old old', 'b.ts': 'untouched'}
    result = apply_edits(base, (
        Replacement('a.ts', 'old', 'next', count=2),
        Replacement('a.ts', 'next next', 'final'),
    ))
    assert result == {'a.ts': 'final', 'b.ts': 'untouched'}
    assert base == {'a.ts': 'old old', 'b.ts': 'untouched'}


@pytest.mark.parametrize('text,expected,actual', [('old old', 1, 2), ('absent', 2, 0)])
def test_drift_names_path_and_counts(text: str, expected: int, actual: int) -> None:
    with pytest.raises(ValueError, match=f'a.ts: expected {expected} matches, actual {actual}'):
        apply_edits({'a.ts': text}, [Replacement('a.ts', 'old', 'new', expected)])


@pytest.mark.parametrize('old,count', [('', 1), ('old', 0), ('old', -1)])
def test_invalid_edit(old: str, count: int) -> None:
    with pytest.raises(ValueError, match='a.ts: edits require'):
        apply_edits({'a.ts': 'old'}, [Replacement('a.ts', old, 'new', count)])


def test_missing_path() -> None:
    with pytest.raises(ValueError, match='missing.ts: edit path does not exist'):
        apply_edits({}, [Replacement('missing.ts', 'old', 'new')])


def test_switch_coverage_and_independent_trees() -> None:
    switches: dict[FactId, tuple[Replacement, ...]] = {
        cell.fact_id: (Replacement('a.ts', 'old', cell.fact_id),) for cell in CELLS
    }
    trees = generate_trees({'a.ts': 'old'}, switches)
    assert len(trees) == 36
    for cell in CELLS:
        assert trees[cell.fact_id] == {'a.ts': cell.fact_id}
    trees[CELLS[0].fact_id]['extra.ts'] = ''
    assert 'extra.ts' not in trees[CELLS[1].fact_id]
    del switches[CELLS[0].fact_id]
    switches[FactId('unknown')] = ()
    with pytest.raises(ValueError, match='switch coverage: missing=.*extra=.*unknown'):
        generate_trees({'a.ts': 'old'}, switches)
