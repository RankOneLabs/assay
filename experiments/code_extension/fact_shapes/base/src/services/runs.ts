import type { Database } from "bun:sqlite";
import type { Job, Principal, Run, RunRollup } from "../domain/models.ts";
import { runJobsSchema, runListSchema, runSchema } from "../domain/validation.ts";
import { conflict, forbidden } from "../domain/errors.ts";
import { JobRepository } from "../repositories/jobs.ts";
import { RunRepository } from "../repositories/runs.ts";
import { EventRepository } from "../repositories/events.ts";
import { RollupEngine } from "../rollup/engine.ts";
import { durationBetween } from "../timing/finish_times.ts";
import { AccessService } from "./access.ts";
import { RunSummaries, type RunSummary } from "./run_summaries.ts";

/** A run as the service shows it: its stored roll-up fields beside its own. */
export type RunView = RunRollup & {
  id: string;
  title: string;
  project: string;
  finishedAt: number | null;
  duration: number | null;
  revision: number;
  createdAt: number;
  updatedAt: number;
};

export function viewRun(run: Run): RunView {
  return {
    ...run.state,
    id: run.id,
    title: run.title,
    project: run.project,
    finishedAt: run.finishedAt,
    duration: durationBetween(run.createdAt, run.finishedAt),
    revision: run.revision,
    createdAt: run.createdAt,
    updatedAt: run.updatedAt,
  };
}

/** A finished run is closed: it takes no new jobs. */
export function requireAcceptingJobs(run: Run): void {
  if (run.state.status === "finished") conflict("a finished run takes no new jobs");
}

export class RunService {
  constructor(
    private readonly db: Database,
    private readonly runs: RunRepository,
    private readonly jobRepository: JobRepository,
    private readonly events: EventRepository,
    private readonly summaries: RunSummaries,
    private readonly rollups: RollupEngine,
    private readonly access: AccessService,
    private readonly now: () => number,
  ) {}

  create(actor: Principal, input: unknown): RunView {
    this.access.require(actor, "case_write");
    const parsed = runSchema.parse(input);
    return this.db.transaction(() => {
      this.runs.create(parsed.id, actor.project, parsed.title, this.now());
      this.rollups.refresh("run", parsed.id);
      return viewRun(this.runs.require(parsed.id));
    })();
  }

  /** Put existing jobs of the project into a run that is not finished. */
  add(actor: Principal, id: string, input: unknown): RunView {
    this.access.require(actor, "case_write");
    const parsed = runJobsSchema.parse(input);
    return this.db.transaction(() => {
      const run = this.require(actor, id);
      requireAcceptingJobs(run);
      for (const jobId of parsed.jobs) {
        const job = this.jobRepository.require(jobId);
        this.access.requireJob(actor, "case_write", job);
        if (job.archivedAt !== null) conflict("archived jobs cannot join a run");
        const now = this.now();
        this.jobRepository.join(jobId, id, now);
        this.events.append(jobId, "job.joined_run", actor.id, { runId: id }, now);
      }
      this.rollups.refresh("run", id);
      return viewRun(this.runs.require(id));
    })();
  }

  get(actor: Principal, id: string): RunView {
    this.access.require(actor, "case_read");
    return viewRun(this.require(actor, id));
  }

  list(actor: Principal, input: unknown = {}) {
    this.access.require(actor, "case_read");
    const parsed = runListSchema.parse(input);
    const result = this.runs.list(actor.project, parsed.status, parsed.limit, parsed.offset);
    return { ...result, items: result.items.map(viewRun) };
  }

  jobs(actor: Principal, id: string): Job[] {
    this.access.require(actor, "case_read");
    return this.jobRepository.inRun(this.require(actor, id).id);
  }

  summary(actor: Principal, id: string): RunSummary {
    this.access.require(actor, "case_read");
    return this.summaries.read(this.require(actor, id));
  }

  private require(actor: Principal, id: string): Run {
    const run = this.runs.require(id);
    if (run.project !== actor.project) forbidden("run belongs to another project");
    return run;
  }
}
