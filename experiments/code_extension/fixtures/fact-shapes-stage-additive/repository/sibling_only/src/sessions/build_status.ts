import { values } from "../../stage/types.ts";
import type { Attempt } from "../domain/models.ts";
import type { SessionService } from "./session_service.ts";
/**
 * Stages whose build status follows the live session. For a job in any other
 * stage, the status recorded on the attempt is reported instead.
 */
const liveStatusStages: readonly string[] = values;
export function buildRunning(
  sessions: SessionService, stage: string, attempt: Pick<Attempt, "sessionId" | "finishedAt">,
): boolean {
  if (liveStatusStages.includes(stage)) return sessions.isBuildRunning(attempt.sessionId);
  return attempt.finishedAt === null;
}
