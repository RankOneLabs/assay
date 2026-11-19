import * as stageTypes from "../../stage/types.ts";
import type { Attempt } from "../domain/models.ts";
import type { SessionService } from "./session_service.ts";
/**
 * Stages whose build status follows the live session. For a job in any other
 * stage, the status recorded on the attempt is reported instead.
 */
const liveStatusStages: readonly string[] = ["queued", "active", "complete"];
export function buildRunning(
  sessions: SessionService, stage: stageTypes.Stage, attempt: Pick<Attempt, "sessionId" | "finishedAt">,
): boolean {
  if (liveStatusStages.includes(stage)) return sessions.isBuildRunning(attempt.sessionId);
  return attempt.finishedAt === null;
}
