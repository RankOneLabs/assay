import * as types from "./types.ts";
export function acceptValue(value: string): types.Stage {
  if (!types.isValue(value)) throw new Error("unsupported stage");
  return value;
}
export function enforceLimit(count: number, limit: number): void {
  if (!Number.isInteger(count) || count < 0 || count > limit) throw new Error("limit exceeded");
}
