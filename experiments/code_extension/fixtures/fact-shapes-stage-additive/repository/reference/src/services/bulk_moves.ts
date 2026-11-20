import * as stageTypes from "../../stage/types.ts";
import { conflict } from "../domain/errors.ts";
/** Bulk stage changes only move jobs that are still open work. */
const movableInBulk = (stage: stageTypes.Stage): boolean => stageTypes.stageTraits[stage].open;
export function requireBulkMovable(id: string, stage: stageTypes.Stage): void {
  if (!movableInBulk(stage)) conflict(`job ${id} cannot be moved in bulk`);
}
