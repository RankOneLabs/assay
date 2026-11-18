"""Generate committed arms, private patches, READMEs and typed holder evidence.

Run from experiments/ with ``python -m code_extension.fact_shapes.generate``, then
``python -m code_extension.fact_shapes.refresh`` for the same scenarios. No tree is
written until every declared edit and holder line has been validated.

Each arm's start tree is the base with only its manipulated holder rewritten into an
independent copy. The reference patch is the complete solution in that arm; each
omission patch is the reference with one fact's file left as the arm has it.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path
from shutil import rmtree

from pydantic import TypeAdapter

from code_extension.authoring import unified_patch
from code_extension.fact_shapes.cells import (
    CELLS,
    Cell,
    FactHolder,
    FactId,
    HolderSpec,
    RepositoryPath,
)
from code_extension.fact_shapes.switches import (
    ANCHOR_LINE,
    SWITCHES,
    fact_lines,
    omission_tree,
    reference_tree,
)
from code_extension.fixture import CHECKPOINT_SHA, materialize, read_tree
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


def arm_patches(cell: Cell, arm: Mapping[str, str]) -> dict[str, str]:
    """The reference and one omission per scored fact, as `git apply` patches."""
    reference = reference_tree(cell, arm)
    patches = {f'{cell.shape}.reference.patch': unified_patch(dict(arm), reference)}
    for fact in (cell.fact_id, cell.anchor_fact_id):
        patches[f'{cell.shape}.drop-{fact}.patch'] = unified_patch(
            dict(arm), omission_tree(cell, arm, reference, fact),
        )
    if len(set(patches.values())) != len(patches):
        raise ValueError(f'{cell.fact_id}: reference and omission patches must differ')
    return patches


def readme(cells: Sequence[Cell]) -> str:
    """Operator notes for one scenario; the arms table comes from the cell plan."""
    first = cells[0]
    rows = ''.join(
        f'| {cell.shape} | {cell.fact_id} | {", ".join(cell.holders)} |\n' for cell in cells
    )
    return (
        f'# {scenario_name(first)}\n\n'
        f'Feature: {first.feature}. Task type: {first.task_type}.\n\n'
        'Do not publish this fixture content, including task text, hidden tests and solution '
        'patches.\n\n'
        'All six arms share the single task.md and hidden/ directory; hidden test bytes must be '
        'identical across arms.\n\n'
        '| Arm | Manipulated fact | Holder |\n| --- | --- | --- |\n'
        f'{rows}\n'
        f'Anchor fact: {first.anchor_fact_id}. Record labels accept the documented characters '
        'up to 80 characters.\n\n'
        f'Every arm declares the value list in {first.feature}/types.ts, and the edit site uses '
        "it. Only the arm's holder keeps an independent copy of the list, read only by its own "
        'behavior; in the other arms that holder derives from the type. Qualification is '
        "recorded under qualification/. Only this arm's manipulated fact and the scenario "
        'anchor are scored by the mutant gate.\n\n'
        'Generated by `python -m code_extension.fact_shapes.generate`; repository/, patches/ '
        'and this file are not edited by hand.\n\n'
        f'Source checkpoint: {CHECKPOINT_SHA}.\n\n'
        'Excluded: network services, deployment and upstream repository history.\n\n'
        'Adaptations: the start tree omits the requested change and the 80-character label '
        'boundary. The reference patch updates the type, the arm\'s holder, the service '
        'literals a rename touches and the label boundary; each omission patch is that '
        "reference with one fact's file left unchanged. Visible checks use values every arm "
        'keeps under the same spelling. Hidden checks and patches remain outside '
        'repository/.\n'
    )


def write_variants(destination: Path, scenarios: frozenset[str] | None = None) -> None:
    """Write scenarios beneath a code_extension-shaped destination.

    With ``scenarios``, only those scenarios' arms, patches and READMEs are rewritten.
    Every tree and the shared holder metadata are still generated and validated, so a
    slice cannot be written from a generator that fails on the cells outside it.
    """
    trees = generate_trees(read_tree(BASE))
    metadata = holders_json(trees)
    patches = {cell.fact_id: arm_patches(cell, trees[cell.fact_id]) for cell in CELLS}
    known = {scenario_name(cell) for cell in CELLS}
    if scenarios is not None and not scenarios <= known:
        raise ValueError(f'unknown scenarios: {sorted(scenarios - known)}')
    for scenario in sorted(scenarios if scenarios is not None else known):
        cells = [cell for cell in CELLS if scenario_name(cell) == scenario]
        root = destination / 'fixtures' / scenario
        if (root / 'patches').exists():
            rmtree(root / 'patches')
        (root / 'patches').mkdir(parents=True)
        for cell in cells:
            arm = root / 'repository' / cell.shape
            if arm.exists():
                rmtree(arm)
            materialize(arm, trees[cell.fact_id])
            for name, patch in patches[cell.fact_id].items():
                (root / 'patches' / name).write_text(patch, encoding='utf-8')
        (root / 'README.md').write_text(readme(cells), encoding='utf-8')
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
