import { z } from "zod";
import type { Principal } from "../domain/models.ts";
import type { Config } from "../config.ts";
import { keySchema } from "../domain/validation.ts";
import { conflict, limitExceeded } from "../domain/errors.ts";
import { PlanningService } from "./planning.ts";
import { BuildService } from "./builds.ts";
import { AccessService } from "./access.ts";
import { JobRepository } from "../repositories/jobs.ts";
import { AttemptRepository } from "../repositories/attempts.ts";
import { SessionService } from "../sessions/session_service.ts";

const dispatchSchema = z.object({
  id: keySchema,
  sessionId: keySchema,
  worker: keySchema,
  owner: keySchema.optional(),
  minimumPriority: z.number().int().min(0).max(100).default(0),
}).strict();

/** Queue dispatch selects a persisted job and delegates all lifecycle writes to builds. */
export class DispatchService {
  constructor(
    private readonly planning: PlanningService,
    private readonly builds: BuildService,
    private readonly access: AccessService,
    private readonly jobs: JobRepository,
    private readonly attempts: AttemptRepository,
    private readonly sessions: SessionService,
    private readonly config: Config,
  ) {}

  running(actor: Principal) {
    this.access.require(actor, "case_read");
    const jobs = this.jobs.list({ project: actor.project, limit: 10000, offset: 0 }).items;
    return jobs.flatMap(job => this.attempts.list(job.id)
      .filter(attempt => this.sessions.isBuildRunning(attempt.sessionId))
      .map(attempt => ({ job, attempt })));
  }

  next(actor: Principal, input: unknown) {
    this.access.require(actor, "case_write");
    this.access.require(actor, "case_read");
    const parsed = dispatchSchema.parse(input);
    const running = this.running(actor);
    if (running.length >= this.config.maxConcurrentBuilds) limitExceeded("concurrent build limit reached");
    if (running.some(item => item.attempt.worker === parsed.worker)) conflict("worker already has a running build");
    const job = this.planning.ready(actor, 1, {
      owner: parsed.owner,
      minPriority: parsed.minimumPriority,
    })[0];
    if (!job) return null;
    const attempt = this.builds.start(actor, job.id, {
      id: parsed.id,
      sessionId: parsed.sessionId,
      worker: parsed.worker,
      expectedRevision: job.revision,
    });
    return { job: this.jobs.require(job.id), attempt };
  }

  capacity(actor: Principal) {
    const running = this.running(actor);
    return {
      maximum: this.config.maxConcurrentBuilds,
      used: running.length,
      available: Math.max(0, this.config.maxConcurrentBuilds - running.length),
      workers: running.map(item => item.attempt.worker).sort(),
    };
  }
}
