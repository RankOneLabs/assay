import { isValue, type Stage } from "./types.ts";
export function acceptValue(value: string): Stage {
  if (!isValue(value) || !["queued", "active", "complete"].includes(value)) throw new Error("unsupported stage");
  return value;
}
export function enforceLimit(count: number, limit: number): void {
  if (!Number.isInteger(count) || count < 0 || count > limit) throw new Error("limit exceeded");
}
