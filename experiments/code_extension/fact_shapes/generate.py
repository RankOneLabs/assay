"""Generate committed arms and typed holder evidence from the reviewed switches.

Run from experiments/ with ``python -m code_extension.fact_shapes.generate``.
No tree is written until every declared edit and holder line has been validated.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path
from shutil import rmtree

from pydantic import TypeAdapter

from code_extension.fact_shapes.cells import (
    CELLS,
    Cell,
    FactHolder,
    FactId,
    HolderSpec,
    RepositoryPath,
)
from code_extension.fact_shapes.switches import ANCHOR_LINE, SWITCHES, fact_lines
from code_extension.fixture import materialize, read_tree
from code_extension.slice import Replacement

DIRECTORY = Path(__file__).resolve().parent
BASE = DIRECTORY / 'base'
HOLDERS = TypeAdapter(list[HolderSpec])


def scenario_name(cell: Cell) -> str:
    """Use hyphenated feature names and the shared task-type scenario."""
    return f'fact-shapes-{cell.feature.replace("_", "-")}-{cell.task_type}'


def apply_edits(base: Mapping[str, str], edits: Sequence[Replacement]) -> dict[str, str]:
    """Apply sequential edits to a copy, rejecting missing paths and base drift."""
    tree = dict(base)
    for edit in edits:
        if edit.path not in tree:
            raise ValueError(f'{edit.path}: edit path does not exist in base tree')
        if not edit.old or edit.count < 1:
            raise ValueError(f'{edit.path}: edits require nonempty old text and positive count')
        actual = tree[edit.path].count(edit.old)
        if actual != edit.count:
            raise ValueError(f'{edit.path}: expected {edit.count} matches, actual {actual}')
        tree[edit.path] = tree[edit.path].replace(edit.old, edit.new, edit.count)
    return tree


def generate_trees(
    base: Mapping[str, str], switches: Mapping[FactId, Sequence[Replacement]] = SWITCHES,
) -> dict[FactId, dict[str, str]]:
    """Generate one independent tree per planned cell, requiring exact coverage."""
    expected = {cell.fact_id for cell in CELLS}
    if set(switches) != expected:
        missing = sorted(expected - set(switches))
        extra = sorted(set(switches) - expected)
        raise ValueError(f'switch coverage: missing={missing}, extra={extra}')
    return {cell.fact_id: apply_edits(base, switches[cell.fact_id]) for cell in CELLS}


def build_holders(trees: Mapping[FactId, Mapping[str, str]]) -> list[HolderSpec]:
    """Build the shared holder-spec type and verify every exact evidence line."""
    result: list[HolderSpec] = []
    for cell in CELLS:
        anchor_path = RepositoryPath(f'{cell.feature}/anchor.ts')
        spec = HolderSpec(
            scenario=scenario_name(cell), shape=cell.shape,
            manipulated=FactHolder(
                cell.fact_id, cell.holders, {path: fact_lines(cell) for path in cell.holders},
            ),
            anchor=FactHolder(cell.anchor_fact_id, (anchor_path,), {anchor_path: (ANCHOR_LINE,)}),
        )
        for fact in (spec.manipulated, spec.anchor):
            for path, lines in fact.fact_lines.items():
                for line in lines:
                    if line not in trees[cell.fact_id][path].splitlines():
                        raise ValueError(f'{cell.fact_id}: {path}: missing fact line {line!r}')
        result.append(spec)
    return result


def holders_json(trees: Mapping[FactId, Mapping[str, str]]) -> str:
    """Serialize deterministic JSON that validates against cells.HolderSpec."""
    return HOLDERS.dump_json(build_holders(trees), indent=2).decode('utf-8') + '\n'


def write_variants(destination: Path, scenarios: frozenset[str] | None = None) -> None:
    """Write scenarios beneath a code_extension-shaped destination.

    With ``scenarios``, only those scenarios' arms are rewritten. Every tree and the
    shared holder metadata are still generated and validated, so a slice cannot be
    written from a generator that fails on the cells outside it.
    """
    trees = generate_trees(read_tree(BASE))
    metadata = holders_json(trees)
    known = {scenario_name(cell) for cell in CELLS}
    if scenarios is not None and not scenarios <= known:
        raise ValueError(f'unknown scenarios: {sorted(scenarios - known)}')
    for cell in CELLS:
        if scenarios is not None and scenario_name(cell) not in scenarios:
            continue
        root = destination / 'fixtures' / scenario_name(cell) / 'repository' / cell.shape
        if root.exists():
            rmtree(root)
        materialize(root, trees[cell.fact_id])
    holder_path = destination / 'fact_shapes/holders.json'
    holder_path.parent.mkdir(parents=True, exist_ok=True)
    holder_path.write_text(metadata, encoding='utf-8')


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--scenario', action='append', dest='scenarios',
        help='Rewrite only this scenario; repeatable. Default: all six.',
    )
    arguments = parser.parse_args()
    write_variants(
        DIRECTORY.parent, frozenset(arguments.scenarios) if arguments.scenarios else None,
    )
