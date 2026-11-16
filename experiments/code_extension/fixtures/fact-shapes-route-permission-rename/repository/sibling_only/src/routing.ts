import type { Stage } from "../stage/types.ts";
export const stageRoutes: Record<Stage, string> = {
  queued: "/jobs/queue",
  active: "/jobs/work",
  complete: "/jobs/archive",
};
export function routeStage(stage: Stage): string { return stageRoutes[stage]; }
