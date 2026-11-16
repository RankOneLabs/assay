import type { Database } from "bun:sqlite";
import type { Principal } from "../domain/models.ts";
import { conflict } from "../domain/errors.ts";
import { plan, impact } from "../domain/graph.ts";
import { JobRepository } from "../repositories/jobs.ts";
import { DependencyRepository } from "../repositories/dependencies.ts";
import { EventRepository } from "../repositories/events.ts";
import { AccessService } from "./access.ts";
import { JobService } from "./jobs.ts";

export class PlanningService {
  constructor(
    private readonly db: Database,
    private readonly jobs: JobRepository,
    private readonly dependencies: DependencyRepository,
    private readonly events: EventRepository,
    private readonly access: AccessService,
    private readonly jobService: JobService,
    private readonly now: () => number,
  ) {}

  add(actor: Principal, id: string, requiresId: string): boolean {
    this.access.require(actor, "case_write");
    return this.db.transaction(() => {
      const job = this.jobs.require(id);
      const requirement = this.jobs.require(requiresId);
      this.access.requireJob(actor, "case_write", job);
      this.access.requireJob(actor, "case_write", requirement);
      this.jobService.requireMutable(job);
      if (requirement.archivedAt !== null) conflict("dependency is archived");
      if (id === requiresId) conflict("job cannot depend on itself");
      const now = this.now();
      const added = this.dependencies.add(id, requiresId, actor.id, now);
      // Validate the whole project graph within the same write transaction.
      this.buildPlan(actor.project);
      if (added) this.events.append(id, "dependency.added", actor.id, { requiresId }, now);
      return added;
    })();
  }

  remove(actor: Principal, id: string, requiresId: string): boolean {
    this.access.require(actor, "case_write");
    return this.db.transaction(() => {
      const job = this.jobs.require(id);
      this.access.requireJob(actor, "case_write", job);
      this.jobService.requireMutable(job);
      const removed = this.dependencies.remove(id, requiresId);
      if (removed) {
        this.events.append(id, "dependency.removed", actor.id, { requiresId }, this.now());
      }
      return removed;
    })();
  }

  projectPlan(actor: Principal) {
    this.access.require(actor, "case_read");
    return this.buildPlan(actor.project);
  }

  private buildPlan(project: string) {
    const jobs = this.jobs.list({ project, limit: 10000, offset: 0 }).items;
    const edges = this.dependencies.list(project);
    return plan(jobs.map(job => job.id), edges);
  }

  jobImpact(actor: Principal, id: string) {
    this.jobService.get(actor, id);
    const jobs = this.jobs.list({ project: actor.project, limit: 10000, offset: 0 }).items;
    return impact(id, jobs.map(job => job.id), this.dependencies.list(actor.project));
  }

  blockers(actor: Principal, id: string) {
    this.jobService.get(actor, id);
    return this.dependencies.requirements(id)
      .map(required => this.jobs.require(required))
      .filter(required => required.stage !== "complete" || required.archivedAt !== null);
  }

  ready(actor: Principal, limit = 25) {
    this.access.require(actor, "case_read");
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > 100) conflict("invalid ready limit");
    const jobs = this.jobs.list({
      project: actor.project,
      stage: "queued",
      archived: false,
      limit: 10000,
      offset: 0,
    }).items;
    return jobs.filter(job => this.blockers(actor, job.id).length === 0).slice(0, limit);
  }
}
