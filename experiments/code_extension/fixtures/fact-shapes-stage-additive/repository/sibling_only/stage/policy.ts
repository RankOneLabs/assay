import { values, type Stage } from "./types.ts";
/** Stages that edit() accepts. */
const acceptedStages: readonly string[] = values;
export function acceptValue(value: string): Stage {
  if (!acceptedStages.includes(value)) throw new Error("unsupported stage");
  return value as Stage;
}
export function enforceLimit(count: number, limit: number): void {
  if (!Number.isInteger(count) || count < 0 || count > limit) throw new Error("limit exceeded");
}
