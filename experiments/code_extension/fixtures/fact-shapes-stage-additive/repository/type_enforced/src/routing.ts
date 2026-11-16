import type { Stage } from "../stage/types.ts";
import { vocabularyStore } from "./vocabulary.ts";
export const stageRoutes = vocabularyStore.record("stage", (_value, index) =>
  ["/jobs/queue", "/jobs/work", "/jobs/archive"][index] ?? "/jobs",
);
export function routeStage(stage: Stage): string { return stageRoutes[stage]; }
