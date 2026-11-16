import { z } from "zod";
import { keySchema } from "../domain/validation.ts";
import type { Database } from "bun:sqlite";
import type { Config } from "../config.ts";
import type { Job, Principal } from "../domain/models.ts";
import { createJobSchema, patchJobSchema, transitionSchema, filterSchema, revisionSchema } from "../domain/validation.ts";
import { conflict, forbidden, limitExceeded } from "../domain/errors.ts";
import { requireTransition } from "../domain/transitions.ts";
import { edit, peerGuard } from "../../stage/edit.ts";
import { peerGuard as siblingAccepts } from "../../stage/sibling.ts";
import { enforceLimit } from "../../stage/policy.ts";
import { JobRepository } from "../repositories/jobs.ts";
import { EventRepository } from "../repositories/events.ts";
import { AccessService } from "./access.ts";

export class JobService {
  constructor(
    private readonly db: Database,
    private readonly jobs: JobRepository,
    private readonly events: EventRepository,
    private readonly access: AccessService,
    private readonly config: Config,
    private readonly now: () => number,
    private readonly liveSessionsFor: (jobId: string) => readonly string[] = () => [],
  ) {}

  create(actor: Principal, input: unknown): Job {
    this.access.require(actor, "case_write");
    const parsed = createJobSchema.parse(input);
    if (parsed.project !== actor.project) forbidden("cannot create in another project");
    return this.db.transaction(() => {
      if (this.jobs.count(actor.project) >= this.config.maxJobs) limitExceeded("project job limit reached");
      const now = this.now();
      const job = this.jobs.create(parsed, "queued", now);
      this.events.append(job.id, "job.created", actor.id, { title: job.title }, now);
      return job;
    })();
  }

  get(actor: Principal, id: string): Job {
    // Check authorization before lookup so unauthorized callers cannot enumerate ids.
    this.access.require(actor, "case_read");
    const job = this.jobs.require(id);
    this.access.requireJob(actor, "case_read", job);
    return job;
  }

  list(actor: Principal, input: unknown) {
    this.access.require(actor, "case_read");
    const filter = filterSchema.parse(input);
    if (filter.project !== undefined && filter.project !== actor.project) forbidden();
    return this.jobs.list({ ...filter, project: actor.project });
  }

  patch(actor: Principal, id: string, input: unknown): Job {
    this.access.require(actor, "case_write");
    const parsed = patchJobSchema.parse(input);
    return this.db.transaction(() => {
      const current = this.jobs.require(id);
      this.access.requireJob(actor, "case_write", current);
      this.requireMutable(current);
      const now = this.now();
      const job = this.jobs.patch(id, parsed, now);
      this.events.append(id, "job.patched", actor.id, { revision: job.revision }, now);
      return job;
    })();
  }

  transition(actor: Principal, id: string, input: unknown, peer = false): Job {
    this.access.require(actor, "case_write");
    const parsed = transitionSchema.parse(input);
    const accepts = peer ? siblingAccepts : peerGuard;
    if (!accepts(parsed.stage)) conflict("operation does not accept this stage");
    edit(id, parsed.stage);
    return this.db.transaction(() => {
      const current = this.jobs.require(id);
      this.access.requireJob(actor, "case_write", current);
      this.requireMutable(current);
      if (this.liveSessionsFor(id).length) conflict("live build owns the job stage");
      requireTransition(current.stage, parsed.stage);
      const now = this.now();
      const job = this.jobs.transition(id, parsed.stage, parsed.expectedRevision, now);
      this.events.append(id, "job.transitioned", actor.id, {
        from: current.stage,
        to: job.stage,
        reason: parsed.reason,
      }, now);
      return job;
    })();
  }

  archive(actor: Principal, id: string, input: unknown): Job {
    this.access.require(actor, "case_admin");
    const parsed = revisionSchema.parse(input);
    return this.db.transaction(() => {
      const current = this.jobs.require(id);
      this.access.requireJob(actor, "case_admin", current);
      if (current.stage === "active") conflict("active jobs cannot be archived");
      const now = this.now();
      const job = this.jobs.archive(id, parsed.expectedRevision, now);
      this.events.append(id, "job.archived", actor.id, {}, now);
      return job;
    })();
  }

  restore(actor: Principal, id: string, input: unknown): Job {
    this.access.require(actor, "case_admin");
    const parsed = revisionSchema.parse(input);
    return this.db.transaction(() => {
      const current = this.jobs.require(id);
      this.access.requireJob(actor, "case_admin", current);
      if (this.jobs.count(actor.project) >= this.config.maxJobs) limitExceeded("project job limit reached");
      const now = this.now();
      const job = this.jobs.restore(id, parsed.expectedRevision, now);
      this.events.append(id, "job.restored", actor.id, {}, now);
      return job;
    })();
  }

  history(actor: Principal, id: string, after = 0, limit = 100) {
    this.get(actor, id);
    enforceLimit(limit, 100);
    if (!Number.isSafeInteger(after) || after < 0) conflict("invalid event cursor");
    return this.events.list(id, after, limit);
  }

  clone(actor: Principal, sourceId: string, input: unknown): Job {
    this.access.require(actor, "case_read");
    this.access.require(actor, "case_write");
    const parsed = z.object({
      id: keySchema,
      title: z.string().trim().min(1).max(240).optional(),
      owner: keySchema.optional(),
    }).strict().parse(input);
    return this.db.transaction(() => {
      const source = this.get(actor, sourceId);
      const copy = this.create(actor, {
        id: parsed.id,
        title: parsed.title ?? source.title,
        owner: parsed.owner ?? source.owner,
        project: source.project,
        description: source.description,
        priority: source.priority,
      });
      this.events.append(copy.id, "job.cloned", actor.id, {
        sourceId,
        sourceRevision: source.revision,
      }, this.now());
      return copy;
    })();
  }

  bulkPatch(actor: Principal, input: unknown): Job[] {
    this.access.require(actor, "case_write");
    const parsed = z.object({
      changes: z.array(z.object({ id: keySchema, patch: patchJobSchema }).strict())
        .min(1).max(this.config.maxBulkJobs),
      reason: z.string().trim().min(1).max(2000),
    }).strict().parse(input);
    const ids = parsed.changes.map(change => change.id);
    if (new Set(ids).size !== ids.length) conflict("duplicate jobs in patch batch");
    return this.db.transaction(() => parsed.changes.map(change => {
      const job = this.patch(actor, change.id, change.patch);
      this.events.append(job.id, "job.bulk_patched", actor.id, {
        reason: parsed.reason,
        revision: job.revision,
      }, this.now());
      return job;
    }))();
  }

  bulkTransition(actor: Principal, input: unknown, peer = false): Job[] {
    this.access.require(actor, "case_write");
    const parsed = z.object({
      changes: z.array(z.object({ id: keySchema, transition: transitionSchema }).strict())
        .min(1).max(this.config.maxBulkJobs),
    }).strict().parse(input);
    const ids = parsed.changes.map(change => change.id);
    if (new Set(ids).size !== ids.length) conflict("duplicate jobs in transition batch");
    return this.db.transaction(() => parsed.changes.map(change =>
      this.transition(actor, change.id, change.transition, peer),
    ))();
  }

  compare(actor: Principal, leftId: string, rightId: string) {
    const left = this.get(actor, leftId);
    const right = this.get(actor, rightId);
    const fields = ["title", "description", "stage", "priority", "owner", "project"] as const;
    return {
      left: { id: left.id, revision: left.revision },
      right: { id: right.id, revision: right.revision },
      changes: fields.filter(field => left[field] !== right[field]).map(field => ({
        field,
        before: left[field],
        after: right[field],
      })),
    };
  }

  timeline(actor: Principal, id: string) {
    const job = this.get(actor, id);
    const events = this.events.all(id);
    const transitions = events.filter(event => event.action === "job.transitioned")
      .map(event => ({ ...event, transition: JSON.parse(event.detail) as { from: string; to: string; reason: string } }));
    return {
      id,
      stage: job.stage,
      createdAt: job.createdAt,
      updatedAt: job.updatedAt,
      revision: job.revision,
      eventCount: events.length,
      transitions,
      actors: [...new Set(events.map(event => event.actor))].sort(),
    };
  }

  requireMutable(job: Job): void {
    if (job.archivedAt !== null) conflict("archived job is read only");
    if (job.stage === "complete") conflict("completed job is read only");
  }
}
