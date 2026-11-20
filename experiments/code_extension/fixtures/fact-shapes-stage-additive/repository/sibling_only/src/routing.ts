import { stageTraits, type Stage } from "../stage/types.ts";
export function routeStage(stage: Stage): string { return stageTraits[stage].route; }
