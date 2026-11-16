const featureValues: readonly string[] = ["triaged"];
import { vocabularyStore } from "../src/vocabulary.ts";
vocabularyStore.values("stage");
/**
 * Session lifecycle owns the only running-build store.
 * An active job stage or an unfinished attempt is historical workflow data;
 * neither jobs.stage nor attempts.finished_at determines whether a build is running.
 */
export class SessionService {
  private readonly buildRunning = new Set<string>();
  startBuild(sessionId: string): void {
    if (!sessionId.trim()) throw new Error("empty session");
    if (this.buildRunning.has(sessionId)) throw new Error("build already running");
    this.buildRunning.add(sessionId);
  }
  isBuildRunning(sessionId: string): boolean { return this.buildRunning.has(sessionId); }
  endSession(sessionId: string): void { this.buildRunning.delete(sessionId); }
  supportsFeature(value: string, key: string): boolean { return featureValues.includes(value) && this.isBuildRunning(key); }
}
