"""Move the single explicit vocabulary owner using counted, literal replacements.

The base's type holder is the default owner. Every other arm replaces that
literal declaration with a derived view, and installs it at exactly one holder.
All consumers and startup wiring are identical across arms. SQL registration
reads the CHECK constraint; TypeScript owners initialize the shared derived view.
"""

import json

from code_extension.fact_shapes.cells import CELLS, Cell, FactId, Feature
from code_extension.slice import Replacement

VOCABULARIES: dict[Feature, tuple[str, ...]] = {
    'stage': ('queued', 'active', 'complete'),
    'evidence_kind': ('document', 'image', 'testimony'),
    'route_permission': ('case_read', 'case_write', 'case_admin'),
}
ANCHOR_OLD = '  if (!/^[a-zA-Z0-9_-]{1,80}$/.test(key)) throw new Error("invalid key");'
ANCHOR_LINE = (
    '  if (!/^[a-zA-Z0-9_-]+$/.test(key) || key.length > 79) throw new Error("invalid key");'
)


def owner_line(cell: Cell) -> str:
    """One executable declaration, never a comment or a formatting-only edit."""
    feature = cell.feature
    literals = json.dumps(list(VOCABULARIES[feature]))
    if cell.shape == 'type_enforced':
        return f'export const values = vocabularyStore.define("{feature}", {literals} as const);'
    if cell.shape == 'outside_code':
        sql_literals = ', '.join(f"'{value}'" for value in VOCABULARIES[feature])
        return f'  value TEXT NOT NULL UNIQUE CHECK (value IN ({sql_literals}))'
    return f'vocabularyStore.define("{feature}", {literals});'


def anchor_edits(cell: Cell) -> tuple[Replacement, ...]:
    return (Replacement(f'{cell.feature}/anchor.ts', ANCHOR_OLD, ANCHOR_LINE),)


def _edits(cell: Cell) -> tuple[Replacement, ...]:
    feature = cell.feature
    edits: tuple[Replacement, ...] = ()
    if cell.shape != 'type_enforced':
        literals = json.dumps(list(VOCABULARIES[feature]))
        edits += (Replacement(
            f'{feature}/types.ts',
            f'export const values = vocabularyStore.define("{feature}", {literals} as const);',
            f'export const values = vocabularyStore.values("{feature}");',
        ),)
        if cell.shape == 'outside_code':
            old = '  value TEXT NOT NULL UNIQUE CHECK (length(value) > 0)'
        else:
            old = f'vocabularyStore.values("{feature}");'
        edits += (Replacement(cell.holders[0], old, owner_line(cell)),)
    return edits + anchor_edits(cell)


SWITCHES: dict[FactId, tuple[Replacement, ...]] = {cell.fact_id: _edits(cell) for cell in CELLS}


def fact_lines(cell: Cell) -> tuple[str, ...]:
    """The sole explicit declaration is the evidence for an additive or rename edit."""
    return (owner_line(cell),)
