import type { Page } from "../domain/models.ts";

/** Wrap one offset page of rows; nextOffset is null on the last page. */
export function page<T>(items: T[], total: number, limit: number, offset: number): Page<T> {
  const end = offset + items.length;
  return { items, total, limit, offset, nextOffset: end < total ? end : null };
}
