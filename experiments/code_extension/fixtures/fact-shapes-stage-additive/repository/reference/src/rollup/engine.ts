import type { Piece } from "./pieces.ts";

export type Fields<C, S> = { readonly [K in keyof S]: Piece<C, S[K]> };

/** One level's roll-up: a piece for every field the level stores. */
export interface Rollup<C, S> {
  readonly fields: Fields<C, S>;
}

export function rollup<C, S>(fields: Fields<C, S>): Rollup<C, S> {
  return { fields };
}

/** A node of the nest: a level name and an id within that level. */
export interface NodeRef {
  level: string;
  id: string;
}

/** How the engine reads and stores one derived level. */
export interface LevelDefinition<C, S> {
  rollup: Rollup<C, S>;
  children(id: string): readonly C[];
  stored(id: string): S | null;
  store(id: string, state: S): void;
  parent(id: string): NodeRef | null;
}

type State = Record<string, unknown>;
type AnyPiece = (children: readonly unknown[], previous?: unknown) => unknown;

interface Level {
  fields: Map<string, AnyPiece>;
  children(id: string): readonly unknown[];
  stored(id: string): State | null;
  store(id: string, state: State): void;
}

/**
 * Keeps every derived level equal to what its declaration computes from its children.
 * A change to a node recomputes its parent, then that parent's parent, up the nest.
 */
export class RollupEngine {
  private readonly parents = new Map<string, (id: string) => NodeRef | null>();
  private readonly levels = new Map<string, Level>();

  /** A level that stores nothing derived, such as the leaves of the nest. */
  leaf(name: string, parent: (id: string) => NodeRef | null): void {
    this.parents.set(name, parent);
  }

  level<C, S>(name: string, definition: LevelDefinition<C, S>): void {
    this.parents.set(name, id => definition.parent(id));
    this.levels.set(name, {
      fields: new Map(Object.entries(definition.rollup.fields) as [string, AnyPiece][]),
      children: id => definition.children(id),
      stored: id => definition.stored(id) as State | null,
      store: (id, state) => definition.store(id, state as S),
    });
  }

  /** Add a field to a level's declaration; nodes get it when they are next refreshed. */
  declare<C, V>(name: string, field: string, piece: Piece<C, V>): void {
    this.require(name).fields.set(field, piece as AnyPiece);
  }

  /** What the node stores once it is recomputed from its current children. */
  compute(name: string, id: string): State {
    const level = this.require(name);
    const previous = level.stored(id) ?? {};
    const children = level.children(id);
    const state: State = {};
    for (const [field, piece] of level.fields) state[field] = piece(children, previous[field]);
    return state;
  }

  /** Recompute and store a node, then bring every ancestor up to date. */
  refresh(name: string, id: string): void {
    this.require(name).store(id, this.compute(name, id));
    this.changed(name, id);
  }

  /** A node changed: refresh its parent, which walks on up the nest. */
  changed(name: string, id: string): void {
    const parent = this.parents.get(name)?.(id) ?? null;
    if (parent !== null) this.refresh(parent.level, parent.id);
  }

  private require(name: string): Level {
    const level = this.levels.get(name);
    if (level === undefined) throw new Error(`unknown roll-up level ${name}`);
    return level;
  }
}
