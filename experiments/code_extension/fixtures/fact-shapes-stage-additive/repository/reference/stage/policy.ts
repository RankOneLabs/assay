import * as types from "./types.ts";
import { conflict } from "../src/domain/errors.ts";
/** Whether a job in this stage can still be changed. */
const openForChanges = (stage: types.Stage): boolean => types.values.indexOf(stage) < 2;
export function acceptValue(value: string): types.Stage {
  if (!types.isValue(value)) throw new Error("unsupported stage");
  if (!openForChanges(value)) conflict("job is read only in this stage");
  return value;
}
export function enforceLimit(count: number, limit: number): void {
  if (!Number.isInteger(count) || count < 0 || count > limit) throw new Error("limit exceeded");
}
