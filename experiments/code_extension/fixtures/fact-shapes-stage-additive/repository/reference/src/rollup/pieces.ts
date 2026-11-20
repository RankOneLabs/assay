/**
 * Reusable roll-up pieces. A piece computes one stored field of a parent from the
 * parent's children; `previous` is the value the parent stored for that field last.
 */
export type Piece<C, V> = (children: readonly C[], previous?: V) => V;

/** How many children there are, or how many pass `test`. */
export const count = <C>(test: (child: C) => boolean = () => true): Piece<C, number> =>
  children => children.filter(test).length;

/** Whether there are children and every one passes `test`. */
export const all = <C>(test: (child: C) => boolean): Piece<C, boolean> =>
  children => children.length > 0 && children.every(test);

/** Whether at least one child passes `test`. */
export const any = <C>(test: (child: C) => boolean): Piece<C, boolean> =>
  children => children.some(test);

/** `value` of the child with the latest `time`; children without a time are skipped. */
export function latest<C, V>(time: (child: C) => number | null, value: (child: C) => V): Piece<C, V | null> {
  return children => {
    let found: { at: number; child: C } | null = null;
    for (const child of children) {
      const at = time(child);
      if (at !== null && (found === null || at >= found.at)) found = { at, child };
    }
    return found === null ? null : value(found.child);
  };
}

/** `yes` or `no`, chosen by `condition` over the children. */
export const when = <C, T>(condition: Piece<C, boolean>, yes: T, no: T): Piece<C, T> =>
  (children, previous) => (previous === yes || condition(children) ? yes : no);
