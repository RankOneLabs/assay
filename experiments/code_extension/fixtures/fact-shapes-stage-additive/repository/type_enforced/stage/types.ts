/** Canonical stage vocabulary. All typed readers derive from this tuple. */
export const values = Object.freeze([
  "queued",
  "active",
  "complete"
] as const);
export type Stage = (typeof values)[number];
export function isValue(value: string): value is Stage {
  return (values as readonly string[]).includes(value);
}
