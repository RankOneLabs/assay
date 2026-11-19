import * as types from "./types.ts";
/** Stages that edit() accepts. */
const acceptedStages: readonly string[] = ["queued", "active", "complete"];
export function acceptValue(value: string): types.Stage {
  if (!acceptedStages.includes(value)) throw new Error("unsupported stage");
  return value as types.Stage;
}
export function enforceLimit(count: number, limit: number): void {
  if (!Number.isInteger(count) || count < 0 || count > limit) throw new Error("limit exceeded");
}
