"""Pure exact-match generation primitives for the fact-shape fixtures.

No tree is written until every declared edit has been validated. Holder metadata
and the command-line writer depend on the shared holder-spec type in cells.py.
"""

from collections.abc import Mapping, Sequence

from code_extension.fact_shapes.cells import CELLS, FactId
from code_extension.slice import Replacement


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
    base: Mapping[str, str], switches: Mapping[FactId, Sequence[Replacement]],
) -> dict[FactId, dict[str, str]]:
    """Generate one independent tree per planned cell, requiring exact coverage."""
    expected = {cell.fact_id for cell in CELLS}
    if set(switches) != expected:
        missing = sorted(expected - set(switches))
        extra = sorted(set(switches) - expected)
        raise ValueError(f'switch coverage: missing={missing}, extra={extra}')
    return {cell.fact_id: apply_edits(base, switches[cell.fact_id]) for cell in CELLS}
