export const values = ["queued", "active", "complete"] as const;
export type Stage = (typeof values)[number];
export function isValue(value: string): value is Stage {
  return (values as readonly string[]).includes(value);
}
