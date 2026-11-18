import { values, type Stage } from "../../stage/types.ts";
import { titleLabels } from "./labels.ts";
/** Display label for each of the stages. */
export const stageLabels: Record<Stage, string> = titleLabels(values);
export function stageLabel(value: Stage): string { return stageLabels[value]; }
