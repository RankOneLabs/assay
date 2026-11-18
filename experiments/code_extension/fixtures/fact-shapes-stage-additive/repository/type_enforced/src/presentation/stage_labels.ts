import type { Stage } from "../../stage/types.ts";
/** Display label for each of the stages. */
export const stageLabels: Record<Stage, string> = { queued: "Queued", active: "Active", complete: "Complete" };
export function stageLabel(value: Stage): string { return stageLabels[value]; }
