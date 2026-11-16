"""Reviewed exact-match holder edits; generated fixture bytes are derived output.

The base owns the canonical vocabulary and sanctioned peer/SQL controls. These
switches materialize an independent policy/registry when selected, preserve the
canonical source and controls, and never introduce a second state source. Both
task types start with the same existing vocabulary: future task values belong
in task solutions, never in these pre-task trees.
"""

from code_extension.fact_shapes.cells import CELLS, Cell, FactId, Feature, Shape
from code_extension.slice import Replacement

_VOCABULARIES: dict[Feature, tuple[str, ...]] = {
    'stage': ('queued', 'active', 'complete'),
    'evidence_kind': ('document', 'image', 'testimony'),
    'route_permission': ('case_read', 'case_write', 'case_admin'),
}
_STORES: dict[Feature, tuple[str, str]] = {
    'stage': ('buildRunning', 'Set<string>'),
    'evidence_kind': ('evidence_kindSelections', 'Map<string, EvidenceKind>'),
    'route_permission': ('route_permissionSelections', 'Map<string, RoutePermission>'),
}
ANCHOR_OLD = '  if (!/^[a-zA-Z0-9_-]{1,80}$/.test(key)) throw new Error("invalid key");'
ANCHOR_LINE = (
    '  if (!/^[a-zA-Z0-9_-]+$/.test(key) || key.length > 80) throw new Error("invalid key");'
)


def _holder_edits(feature: Feature) -> dict[Shape, tuple[Replacement, ...]]:
    values = _VOCABULARIES[feature]
    literals = ', '.join(f'"{value}"' for value in values)
    tuple_old = f'export const values = [{literals}] as const;'
    tuple_new = 'export const values = Object.freeze([\n' + ',\n'.join(
        f'  "{value}"' for value in values
    ) + '\n] as const);'
    guard_old = f'  if (!isValue(value)) throw new Error("unsupported {feature}");'
    guard_new = (
        f'  if (!isValue(value) || ![{literals}].includes(value)) '
        f'throw new Error("unsupported {feature}");'
    )
    registry_old = (
        'export const descriptiveRegistry: Readonly<Record<string, string>> = Object.fromEntries(\n'
        '  values.map(value => [value, `/jobs/${value}`]),\n);'
    )
    registry_new = (
        'export const descriptiveRegistry: Readonly<Record<string, string>> = {\n'
    ) + ''.join(
        f'  "{value}": "/jobs/{value}",\n' for value in values
    ) + '};'
    cases_old = ''.join(f'    case "{value}":\n' for value in values) + '      return true;'
    cases_new = '\n'.join(f'    case "{value}": return true;' for value in values)
    sql_old = ', '.join(f"'{value}'" for value in values)
    sql_new = '\n' + ',\n'.join(f"    '{value}'" for value in values) + '\n  '
    symbol, store_type = _STORES[feature]
    # The annotations expose the existing store's role without adding storage.
    state_old = f'  private readonly {symbol} = new {store_type}();'
    state_new = f'  private readonly {symbol}: {store_type} = new {store_type}();'
    return {
        'type_enforced': (Replacement(f'{feature}/types.ts', tuple_old, tuple_new),),
        'reference': (Replacement(f'{feature}/policy.ts', guard_old, guard_new),),
        'name_only': (
            Replacement(f'{feature}/names.ts', 'import { values, isValue }', 'import { isValue }'),
            Replacement(f'{feature}/names.ts', registry_old, registry_new),
            Replacement(
                f'{feature}/names.ts', '  return isValue(value);',
                '  return Object.hasOwn(descriptiveRegistry, value) && isValue(value);',
            ),
        ),
        'sibling_only': (Replacement(f'{feature}/sibling.ts', cases_old, cases_new),),
        'outside_code': (Replacement(f'{feature}/001_constraint.sql', sql_old, sql_new),),
        'existing_state': (Replacement(f'{feature}/state.ts', state_old, state_new),),
    }


def anchor_edits(cell: Cell) -> tuple[Replacement, ...]:
    """The same reference holder edit is applied to every arm of a scenario."""
    return (Replacement(f'{cell.feature}/anchor.ts', ANCHOR_OLD, ANCHOR_LINE),)


SWITCHES: dict[FactId, tuple[Replacement, ...]] = {
    cell.fact_id: _holder_edits(cell.feature)[cell.shape] + anchor_edits(cell)
    for cell in CELLS
}


def fact_lines(cell: Cell) -> tuple[str, ...]:
    """Existing lines that a correct holder update must extend, copy or rename."""
    edits = _holder_edits(cell.feature)[cell.shape]
    if cell.shape == 'name_only':
        return tuple(line for line in edits[1].new.splitlines() if line.startswith('  "'))
    if cell.shape == 'type_enforced':
        return tuple(line for line in edits[0].new.splitlines() if line.startswith('  "'))
    if cell.shape == 'existing_state':
        # Readers are part of rename evidence as well as the storage declaration.
        readers: tuple[str, ...]
        if cell.feature == 'stage':
            readers = (
                '    if (this.buildRunning.has(sessionId)) '
                'throw new Error("build already running");',
                '    this.buildRunning.add(sessionId);',
                '  isBuildRunning(sessionId: string): boolean { '
                'return this.buildRunning.has(sessionId); }',
                '  endSession(sessionId: string): void { this.buildRunning.delete(sessionId); }',
            )
        else:
            type_name = 'EvidenceKind' if cell.feature == 'evidence_kind' else 'RoutePermission'
            symbol, _ = _STORES[cell.feature]
            readers = (
                f'  set(key: string, value: {type_name}): void {{ '
                f'this.{symbol}.set(key, value); }}',
                f'  get(key: string): {type_name} | undefined {{ return this.{symbol}.get(key); }}',
                f'  remove(key: string): void {{ this.{symbol}.delete(key); }}',
            )
        return (edits[0].new, *readers)
    return tuple(line for line in edits[0].new.splitlines() if line.strip())
