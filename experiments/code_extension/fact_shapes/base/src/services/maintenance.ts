import { DependencyRepository } from "../repositories/dependencies.ts";
import { plan } from "../domain/graph.ts";
import { checksum } from "../domain/checksum.ts";
import type { Database } from "bun:sqlite";
import type { Principal } from "../domain/models.ts";
import type { Config } from "../config.ts";
import { bulkSchema } from "../domain/validation.ts";
import { conflict, limitExceeded } from "../domain/errors.ts";
import { JobRepository } from "../repositories/jobs.ts";
import { EventRepository } from "../repositories/events.ts";
import { EvidenceRepository } from "../repositories/evidence.ts";
import { AttemptRepository } from "../repositories/attempts.ts";
import { AccessService } from "./access.ts";
import { SessionService } from "../sessions/session_service.ts";

export class MaintenanceService {
  constructor(
    private readonly db: Database,
    private readonly jobs: JobRepository,
    private readonly events: EventRepository,
    private readonly evidence: EvidenceRepository,
    private readonly attempts: AttemptRepository,
    private readonly sessions: SessionService,
    private readonly access: AccessService,
    private readonly config: Config,
    private readonly now: () => number,
    private readonly dependencies: DependencyRepository,
  ) {}

  archive(actor: Principal, input: unknown): string[] {
    this.access.require(actor, "case_admin");
    const parsed = bulkSchema.parse(input);
    if (parsed.ids.length > this.config.maxBulkJobs) limitExceeded("bulk job limit reached");
    return this.db.transaction(() => {
      const now = this.now();
      for (const id of parsed.ids) {
        const job = this.jobs.require(id);
        this.access.requireJob(actor, "case_admin", job);
        if (job.stage === "active") conflict("cannot bulk archive active job");
        this.jobs.archive(id, job.revision, now);
        this.events.append(id, "job.archived", actor.id, { reason: parsed.reason }, now);
      }
      return parsed.ids;
    })();
  }

  purge(actor: Principal, before: number, limit: number): string[] {
    this.access.require(actor, "case_admin");
    if (!Number.isSafeInteger(before) || before < 0 || before > this.now()) conflict("invalid retention cutoff");
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > this.config.maxBulkJobs) {
      limitExceeded("invalid purge batch size");
    }
    return this.db.transaction(() => {
      const eligible = new Set(this.jobs.olderArchived(before, -1, actor.project));
      // Keep prerequisites reachable from retained jobs, including through other archives.
      let changed = true;
      while (changed) {
        changed = false;
        for (const id of eligible) {
          if (this.dependencies.dependents(id).some(dependent => !eligible.has(dependent))) {
            eligible.delete(id);
            changed = true;
          }
        }
      }
      const edges = this.dependencies.list(actor.project)
        .filter(edge => eligible.has(edge.jobId) && eligible.has(edge.requiresId));
      // Delete consumers before prerequisites so every intermediate batch preserves FKs.
      const candidates = plan([...eligible], edges).layers.reverse().flatMap(layer =>
        layer.sort((left, right) => {
          const leftTime = this.jobs.require(left).archivedAt!;
          const rightTime = this.jobs.require(right).archivedAt!;
          return leftTime - rightTime || left.localeCompare(right);
        }),
      ).slice(0, limit);
      for (const id of candidates) {
        for (const attempt of this.attempts.list(id)) {
          if (this.sessions.isBuildRunning(attempt.sessionId)) conflict("job has a running session");
        }
        this.jobs.delete(id);
      }
      return candidates;
    })();
  }

  integrity(actor: Principal) {
    this.access.require(actor, "case_admin");
    const page = this.jobs.list({ project: actor.project, limit: 10000, offset: 0 });
    const issues: { jobId: string; evidenceId: string; message: string }[] = [];
    for (const job of page.items) {
      for (const item of this.evidence.list(job.id)) {
        if (item.checksum !== checksum(item.content)) {
          issues.push({ jobId: job.id, evidenceId: item.id, message: "evidence checksum mismatch" });
        }
        if (item.content.length === 0) {
          issues.push({ jobId: job.id, evidenceId: item.id, message: "empty evidence" });
        }
      }
    }
    return { checked: page.items.length, issues };
  }
}
