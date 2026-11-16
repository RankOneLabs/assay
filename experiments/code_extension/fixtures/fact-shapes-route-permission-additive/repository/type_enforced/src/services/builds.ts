import { z } from "zod";
import { keySchema } from "../domain/validation.ts";
import type { Database } from "bun:sqlite";
import type { Principal } from "../domain/models.ts";
import { buildSchema, finishSchema } from "../domain/validation.ts";
import { conflict, missing, revisionMatches } from "../domain/errors.ts";
import { JobRepository } from "../repositories/jobs.ts";
import { AttemptRepository } from "../repositories/attempts.ts";
import { EventRepository } from "../repositories/events.ts";
import { SessionService } from "../../stage/state.ts";
import { AccessService } from "./access.ts";

export class BuildService {
  constructor(
    private readonly db: Database,
    private readonly jobs: JobRepository,
    private readonly attempts: AttemptRepository,
    private readonly events: EventRepository,
    private readonly sessions: SessionService,
    private readonly access: AccessService,
    private readonly now: () => number,
  ) {}

  start(actor: Principal, jobId: string, input: unknown) {
    this.access.require(actor, "case_write");
    const parsed = buildSchema.parse(input);
    const job = this.jobs.require(jobId);
    this.access.requireJob(actor, "case_write", job);
    revisionMatches(job.revision, parsed.expectedRevision);
    if (job.archivedAt !== null || job.stage !== "queued") conflict("build requires a queued job");
    if (this.sessions.isBuildRunning(parsed.sessionId)) conflict("session already running");
    const result = this.db.transaction(() => {
      const now = this.now();
      const attempt = this.attempts.create(parsed.id, jobId, parsed.sessionId, parsed.worker, now);
      this.jobs.transition(jobId, "active", parsed.expectedRevision, now);
      this.events.append(jobId, "build.started", actor.id, {
        attemptId: attempt.id,
        sessionId: attempt.sessionId,
        worker: attempt.worker,
      }, now);
      return attempt;
    })();
    // Store running status only after durable writes commit successfully.
    this.sessions.startBuild(parsed.sessionId);
    return result;
  }

  finish(actor: Principal, jobId: string, input: unknown) {
    this.access.require(actor, "case_write");
    const parsed = finishSchema.parse(input);
    const job = this.jobs.require(jobId);
    this.access.requireJob(actor, "case_write", job);
    const attempt = this.attempts.bySession(parsed.sessionId) ?? missing("session", parsed.sessionId);
    if (attempt.jobId !== jobId) missing("session", parsed.sessionId);
    if (!this.sessions.isBuildRunning(parsed.sessionId)) conflict("session is not running");
    if (job.stage !== "active") conflict("job is no longer active");
    const result = this.db.transaction(() => {
      const now = this.now();
      const finished = this.attempts.finish(parsed.sessionId, parsed.exitCode, parsed.output, now);
      const stage = parsed.exitCode === 0 ? "complete" : "queued";
      this.jobs.transition(jobId, stage, job.revision, now);
      this.events.append(jobId, "build.finished", actor.id, {
        attemptId: finished.id,
        exitCode: parsed.exitCode,
        stage,
      }, now);
      return finished;
    })();
    this.sessions.endSession(parsed.sessionId);
    return result;
  }

  list(actor: Principal, jobId: string) {
    this.access.requireJob(actor, "case_read", this.jobs.require(jobId));
    return this.attempts.list(jobId).map(attempt => ({
      ...attempt,
      running: this.sessions.isBuildRunning(attempt.sessionId),
    }));
  }

  cancel(actor: Principal, jobId: string, sessionId: string, reason: unknown) {
    this.access.require(actor, "case_write");
    keySchema.parse(sessionId);
    const message = z.string().trim().min(1).max(2000).parse(reason);
    const job = this.jobs.require(jobId);
    this.access.requireJob(actor, "case_write", job);
    const attempt = this.attempts.bySession(sessionId) ?? missing("session", sessionId);
    if (attempt.jobId !== jobId) missing("session", sessionId);
    if (!this.sessions.isBuildRunning(sessionId)) conflict("session is not running");
    if (job.stage !== "active") conflict("job is no longer active");
    const result = this.db.transaction(() => {
      const now = this.now();
      const cancelled = this.attempts.finish(sessionId, 130, message, now);
      this.jobs.transition(jobId, "queued", job.revision, now);
      this.events.append(jobId, "build.cancelled", actor.id, {
        attemptId: attempt.id,
        sessionId,
        reason: message,
      }, now);
      return cancelled;
    })();
    this.sessions.endSession(sessionId);
    return result;
  }

  recover(actor: Principal, jobId: string, reason: unknown) {
    this.access.require(actor, "case_admin");
    const message = z.string().trim().min(1).max(2000).parse(reason);
    return this.db.transaction(() => {
      const job = this.jobs.require(jobId);
      this.access.requireJob(actor, "case_admin", job);
      const attempts = this.attempts.list(jobId);
      if (attempts.some(attempt => this.sessions.isBuildRunning(attempt.sessionId))) {
        conflict("cannot recover a live session");
      }
      if (job.archivedAt !== null) conflict("cannot recover an archived job");
      if (job.stage !== "active") conflict("recovery requires an active job");
      const now = this.now();
      const recovered = attempts.filter(attempt => attempt.finishedAt === null).map(attempt =>
        this.attempts.finish(attempt.sessionId, 255, message, now),
      );
      this.jobs.transition(jobId, "queued", job.revision, now);
      this.events.append(jobId, "build.recovered", actor.id, {
        attempts: recovered.map(attempt => attempt.id),
        reason: message,
      }, now);
      return { job: this.jobs.require(jobId), attempts: recovered };
    })();
  }

  output(actor: Principal, jobId: string, attemptId: string, offset = 0, limit = 4096) {
    this.access.requireJob(actor, "case_read", this.jobs.require(jobId));
    if (!Number.isSafeInteger(offset) || offset < 0) conflict("invalid output offset");
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > 10000) conflict("invalid output limit");
    const attempt = this.attempts.require(attemptId);
    if (attempt.jobId !== jobId) missing("attempt", attemptId);
    const text = attempt.output.slice(offset, offset + limit);
    return {
      attemptId,
      offset,
      text,
      total: attempt.output.length,
      nextOffset: offset + text.length < attempt.output.length ? offset + text.length : null,
      running: this.sessions.isBuildRunning(attempt.sessionId),
    };
  }

  summary(actor: Principal, jobId: string) {
    const attempts = this.list(actor, jobId);
    return {
      jobId,
      total: attempts.length,
      running: attempts.filter(attempt => attempt.running).length,
      succeeded: attempts.filter(attempt => attempt.exitCode === 0).length,
      failed: attempts.filter(attempt => attempt.exitCode !== null && attempt.exitCode > 0).length,
      unfinished: attempts.filter(attempt => attempt.finishedAt === null).length,
      workers: [...new Set(attempts.map(attempt => attempt.worker))].sort(),
      duration: attempts.reduce((sum, attempt) =>
        sum + (attempt.finishedAt === null ? 0 : attempt.finishedAt - attempt.startedAt), 0),
    };
  }

  /** Shutdown clears the owner, leaving attempt history as historical data only. */
  end(actor: Principal, jobId: string, sessionId: string): void {
    this.access.requireJob(actor, "case_write", this.jobs.require(jobId));
    const attempt = this.attempts.bySession(sessionId) ?? missing("session", sessionId);
    if (attempt.jobId !== jobId) missing("session", sessionId);
    this.sessions.endSession(sessionId);
  }
}
