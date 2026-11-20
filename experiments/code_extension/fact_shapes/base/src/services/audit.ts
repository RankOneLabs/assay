import type { Principal } from "../domain/models.ts";
import type { AuditEvent, AuditFilter, AuditGroup, StageHistory } from "../domain/audit.ts";
import {
  auditPageSchema, auditExportSchema, auditSummarySchema, auditEvent, toNdjson, stageHistory, stageDwell,
} from "../domain/audit.ts";
import { AuditRepository } from "../repositories/audit.ts";
import { JobRepository } from "../repositories/jobs.ts";
import { AccessService } from "./access.ts";

/** Project administrators review who did what, when, across every job in the project. */
export class AuditService {
  constructor(
    private readonly audit: AuditRepository,
    private readonly jobs: JobRepository,
    private readonly access: AccessService,
    private readonly now: () => number,
  ) {}

  events(actor: Principal, query: unknown): { items: AuditEvent[]; nextCursor: number | null } {
    this.access.require(actor, "case_admin");
    const { after, limit, ...filter } = auditPageSchema.parse(query);
    return this.read(actor.project, filter, after, limit);
  }

  summary(actor: Principal, query: unknown): { by: string; total: number; groups: AuditGroup[] } {
    this.access.require(actor, "case_admin");
    const { by, ...filter } = auditSummarySchema.parse(query);
    const groups = this.audit.summarize(actor.project, filter, by);
    return { by, total: groups.reduce((sum, group) => sum + group.count, 0), groups };
  }

  stages(actor: Principal, jobId: string): StageHistory {
    this.access.require(actor, "case_admin");
    const job = this.jobs.require(jobId);
    this.access.requireJob(actor, "case_admin", job);
    return stageHistory(job, this.audit.transitions(jobId), this.now());
  }

  /** Time spent per stage over every job in the project, archived jobs included. */
  dwell(actor: Principal): ReturnType<typeof stageDwell> {
    this.access.require(actor, "case_admin");
    const transitions = this.audit.projectTransitions(actor.project);
    const now = this.now();
    return stageDwell(this.jobs.allInProject(actor.project).map(job =>
      stageHistory(job, transitions.get(job.id) ?? [], now),
    ));
  }

  /** NDJSON for offline review; a caller resumes from `nextCursor` until it is null. */
  export(actor: Principal, query: unknown): { body: string; count: number; nextCursor: number | null } {
    this.access.require(actor, "case_admin");
    const { after, limit, ...filter } = auditExportSchema.parse(query);
    const page = this.read(actor.project, filter, after, limit);
    return { body: toNdjson(page.items), count: page.items.length, nextCursor: page.nextCursor };
  }

  /** One row past the limit tells whether another page exists without a second count query. */
  private read(project: string, filter: AuditFilter, after: number, limit: number) {
    const rows = this.audit.page(project, filter, after, limit + 1);
    const items = rows.slice(0, limit).map(auditEvent);
    return { items, nextCursor: rows.length > limit ? items.at(-1)!.sequence : null };
  }
}
