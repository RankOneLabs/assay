"""Exact-edit generation rejects drift before changing the supplied base."""

import re
from collections.abc import Mapping
from itertools import combinations
from pathlib import Path

import pytest
from code_extension.fact_shapes.audit import audit, load_inventory
from code_extension.fact_shapes.cells import CELLS, Cell, FactId, HolderSpec, Shape
from code_extension.fact_shapes.generate import (
    BASE,
    DIRECTORY,
    HOLDERS,
    apply_edits,
    build_holders,
    generate_trees,
    scenario_name,
    write_variants,
)
from code_extension.fact_shapes.switches import SWITCHES, anchor_edits
from code_extension.fixture import read_tree
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


ROOT = DIRECTORY.parent
SCENARIOS = tuple(dict.fromkeys(scenario_name(cell) for cell in CELLS))
_EXPORT = re.compile(
    r'\bexport\s+(?:async\s+)?(?:const|let|function|class|interface|type|enum)\s+(\w+)'
)


def arm_path(cell: Cell) -> Path:
    return ROOT / 'fixtures' / scenario_name(cell) / 'repository' / cell.shape


@pytest.fixture(scope='module')
def committed() -> dict[FactId, dict[str, str]]:
    return {cell.fact_id: read_tree(arm_path(cell)) for cell in CELLS}


@pytest.fixture(scope='module')
def specs() -> list[HolderSpec]:
    return HOLDERS.validate_json((DIRECTORY / 'holders.json').read_bytes())


def assert_holder_only(
    left: Mapping[str, str], right: Mapping[str, str], holders: set[str],
) -> None:
    assert left.keys() == right.keys(), f'file paths differ: {set(left) ^ set(right)}'
    for path in left:
        if left[path] != right[path]:
            assert path in holders, f'out-of-holder edit: {path}'
        if path.endswith(('.ts', '.tsx')):
            assert set(_EXPORT.findall(left[path])) == set(_EXPORT.findall(right[path])), path


def assert_state_unimported(tree: Mapping[str, str], edit_site: str, source: str) -> None:
    from code_extension.fact_shapes.distance import import_hops

    assert import_hops(tree, edit_site, [source]) is None, f'{edit_site} imports {source}'


def test_real_switch_coverage_and_paths() -> None:
    base = read_tree(BASE)
    assert set(SWITCHES) == {cell.fact_id for cell in CELLS}
    for cell in CELLS:
        assert SWITCHES[cell.fact_id]
        assert anchor_edits(cell) == SWITCHES[cell.fact_id][-1:]
        for edit in SWITCHES[cell.fact_id]:
            assert edit.path in base, (cell.fact_id, edit.path)
            assert edit.path in {*cell.holders, f'{cell.feature}/anchor.ts'}
        # One line of the holder differs between arms: the switch is a single edit.
        holder_edits = [edit for edit in SWITCHES[cell.fact_id] if edit.path in cell.holders]
        assert len(holder_edits) == 1 and '\n' not in holder_edits[0].old.strip('\n')
    # Every declared count is exercised; there is no fallback on base drift.
    generated = generate_trees(base)
    assert generated == {cell.fact_id: read_tree(arm_path(cell)) for cell in CELLS}
    drifted = dict(base)
    first = SWITCHES[CELLS[0].fact_id][0]
    drifted[first.path] = drifted[first.path].replace(first.old, '')
    with pytest.raises(ValueError, match=f'{first.path}: expected 1 matches, actual 0'):
        generate_trees(drifted)


def test_regeneration_bytes(tmp_path: Path) -> None:
    write_variants(tmp_path)
    for generated in sorted(tmp_path.rglob('*')):
        if generated.is_file():
            relative = generated.relative_to(tmp_path)
            assert generated.read_bytes() == (ROOT / relative).read_bytes(), str(relative)
    for scenario in SCENARIOS:
        relative = Path('fixtures') / scenario / 'repository'
        generated_paths = {p.relative_to(tmp_path) for p in (tmp_path / relative).rglob('*')}
        committed_paths = {p.relative_to(ROOT) for p in (ROOT / relative).rglob('*')}
        assert generated_paths == committed_paths


def test_scenario_selection_writes_only_that_slice(tmp_path: Path) -> None:
    selected = SCENARIOS[0]
    write_variants(tmp_path, frozenset({selected}))
    assert {p.name for p in (tmp_path / 'fixtures').iterdir()} == {selected}
    assert (tmp_path / 'fact_shapes/holders.json').read_bytes() == (
        ROOT / 'fact_shapes/holders.json').read_bytes()
    with pytest.raises(ValueError, match='unknown scenarios'):
        write_variants(tmp_path, frozenset({'fact-shapes-missing'}))


def test_six_by_six_layout() -> None:
    from typing import get_args

    assert {p.name for p in (ROOT / 'fixtures').glob('fact-shapes-*')} == set(SCENARIOS)
    assert len(SCENARIOS) == 6
    for scenario in SCENARIOS:
        repository = ROOT / 'fixtures' / scenario / 'repository'
        assert {p.name for p in repository.iterdir()} == set(get_args(Shape))
        for arm in repository.iterdir():
            assert read_tree(arm)


def test_holder_specs(
    committed: dict[FactId, dict[str, str]], specs: list[HolderSpec],
) -> None:
    assert len(specs) == 36
    assert specs == build_holders(committed)
    assert len({(spec.scenario, spec.shape) for spec in specs}) == 36
    for cell, spec in zip(CELLS, specs, strict=True):
        assert (spec.scenario, spec.shape) == (scenario_name(cell), cell.shape)
        assert spec.manipulated.fact_id == cell.fact_id
        assert spec.manipulated.holder_paths == cell.holders
        assert spec.anchor.fact_id == cell.anchor_fact_id
        assert spec.anchor.holder_paths == (f'{cell.feature}/anchor.ts',)
        for fact in (spec.manipulated, spec.anchor):
            assert fact.fact_lines
            for path, lines in fact.fact_lines.items():
                for line in lines:
                    assert line in committed[cell.fact_id][path].splitlines(), (cell.fact_id, path)


@pytest.mark.parametrize('scenario', SCENARIOS)
def test_all_arm_pairs(scenario: str, committed: dict[FactId, dict[str, str]]) -> None:
    cells = [cell for cell in CELLS if scenario_name(cell) == scenario]
    for left, right in combinations(cells, 2):
        assert_holder_only(
            committed[left.fact_id], committed[right.fact_id], {*left.holders, *right.holders},
        )
        anchor = f'{left.feature}/anchor.ts'
        assert anchor not in {*left.holders, *right.holders}
        assert committed[left.fact_id][anchor] == committed[right.fact_id][anchor]
        assert anchor_edits(left) == anchor_edits(right)


def test_out_of_holder_mutation_is_reported(committed: dict[FactId, dict[str, str]]) -> None:
    left, right = CELLS[:2]
    mutated = dict(committed[right.fact_id])
    mutated['package.json'] += '\n'
    with pytest.raises(AssertionError, match='out-of-holder edit: package.json'):
        assert_holder_only(committed[left.fact_id], mutated, {*left.holders, *right.holders})


@pytest.mark.parametrize('cell', [cell for cell in CELLS if cell.shape == 'existing_state'],
                         ids=lambda cell: cell.fact_id)
def test_state_source_is_not_imported(cell: Cell, committed: dict[FactId, dict[str, str]]) -> None:
    inventory = load_inventory(DIRECTORY / 'audit_inventory.json')
    name = {'stage': 'session_build', 'evidence_kind': 'default_selection',
            'route_permission': 'default_selection'}[cell.feature]
    sources = [state.source for state in inventory.states if state.name == name]
    assert len(sources) == 1
    assert_state_unimported(committed[cell.fact_id], cell.edit_site, sources[0])
    assert_state_unimported(committed[cell.fact_id], cell.edit_site, cell.holders[0])


@pytest.mark.parametrize('indirect', [False, True])
def test_imported_state_is_reported(indirect: bool) -> None:
    tree = {'edit.ts': 'import "./state.ts";', 'state.ts': ''}
    if indirect:
        tree['edit.ts'] = 'import "./bridge";'
        tree['bridge.ts'] = 'export * from "./state.ts";'
    with pytest.raises(AssertionError, match='edit.ts imports state.ts'):
        assert_state_unimported(tree, 'edit.ts', 'state.ts')


@pytest.mark.parametrize('cell', CELLS, ids=lambda cell: cell.fact_id)
def test_variant_audit(cell: Cell) -> None:
    inventory = load_inventory(DIRECTORY / 'audit_inventory.json')
    findings = audit(arm_path(cell), inventory)
    assert all(finding.path in cell.holders for finding in findings), findings


def test_base_remains_clean() -> None:
    assert audit(BASE, load_inventory(DIRECTORY / 'audit_inventory.json')) == ()


def test_holder_spec_validation() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match='fact lines must cover'):
        HOLDERS.validate_python([{
            'scenario': SCENARIOS[0], 'shape': 'reference',
            'manipulated': {'fact_id': 'example', 'holder_paths': ['a.ts'], 'fact_lines': {}},
            'anchor': {'fact_id': 'anchor', 'holder_paths': ['b.ts'],
                       'fact_lines': {'b.ts': ['existing line']}},
        }])


@pytest.mark.parametrize('cell', CELLS, ids=lambda cell: cell.fact_id)
def test_only_selected_holder_explicitly_owns_fact(
    cell: Cell, committed: dict[FactId, dict[str, str]],
) -> None:
    from code_extension.fact_shapes.audit import explicit_fact_count

    inventory = load_inventory(DIRECTORY / 'audit_inventory.json')
    for concept in inventory.concepts:
        owners = {
            path: count for path, source in committed[cell.fact_id].items()
            if path.endswith(('.ts', '.sql'))
            and (count := explicit_fact_count(source, concept.members))
        }
        expected = {concept.declaring_file: 1}
        if concept.name == cell.feature:
            expected[cell.holders[0]] = 1
        assert owners == expected, (cell.fact_id, concept.name, owners)


def test_regeneration_removes_obsolete_files(tmp_path: Path) -> None:
    write_variants(tmp_path)
    for cell in CELLS:
        scenario = tmp_path / 'fixtures' / scenario_name(cell)
        arm = scenario / 'repository' / cell.shape
        (arm / 'removed.ts').write_text('obsolete')
        (arm / 'old').mkdir()
        (arm / 'old/index.ts').write_text('renamed source')
        (arm / cell.edit_site).write_text('stale bytes')
        (scenario / 'task.md').write_text('preserve shared task')
        (scenario / 'hidden').mkdir(exist_ok=True)
        (scenario / 'hidden/check.ts').write_text('preserve shared tests')
    write_variants(tmp_path)
    for cell in CELLS:
        scenario = tmp_path / 'fixtures' / scenario_name(cell)
        arm = scenario / 'repository' / cell.shape
        assert not (arm / 'removed.ts').exists()
        assert not (arm / 'old').exists()
        assert read_tree(arm) == read_tree(arm_path(cell))
        assert (scenario / 'task.md').read_text() == 'preserve shared task'
        assert (scenario / 'hidden/check.ts').read_text() == 'preserve shared tests'
