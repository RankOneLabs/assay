import * as stageTypes from "../../stage/types.ts";

export function progressByStage<T extends string>(traits: Record<T, { progress: stageTypes.Progress }>): Record<T, stageTypes.Progress> {
  return Object.fromEntries(Object.entries<{ progress: stageTypes.Progress }>(traits)
    .map(([value, trait]) => [value, trait.progress])) as Record<T, stageTypes.Progress>;
}

/** How a job in each stage counts toward its run: still open, or done. */
export const stageProgress: Record<stageTypes.Stage, stageTypes.Progress> = progressByStage(stageTypes.stageTraits);

export function isOpenWork(stage: stageTypes.Stage): boolean { return stageProgress[stage] === "open"; }
export function isDoneWork(stage: stageTypes.Stage): boolean { return stageProgress[stage] === "done"; }
