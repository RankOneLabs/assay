/** Session lifecycle owns the only running-build store. */
export class SessionService {
  private readonly buildRunning = new Set<string>();
  startBuild(sessionId: string): void {
    if (!sessionId.trim()) throw new Error("empty session");
    if (this.buildRunning.has(sessionId)) throw new Error("build already running");
    this.buildRunning.add(sessionId);
  }
  isBuildRunning(sessionId: string): boolean { return this.buildRunning.has(sessionId); }
  endSession(sessionId: string): void { this.buildRunning.delete(sessionId); }
}
