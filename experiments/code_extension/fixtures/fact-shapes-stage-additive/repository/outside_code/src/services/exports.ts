import type { Database } from "bun:sqlite";
import type { Principal, JobBundle } from "../domain/models.ts";
import type { Config } from "../config.ts";
import { checksum, matchesChecksum } from "../domain/checksum.ts";
import { conflict, limitExceeded } from "../domain/errors.ts";
import { JobRepository } from "../repositories/jobs.ts";
import { EvidenceRepository } from "../repositories/evidence.ts";
import { EventRepository } from "../repositories/events.ts";
import { AttemptRepository } from "../repositories/attempts.ts";
import { AccessService } from "./access.ts";
import { ExportSnapshots } from "./export_snapshots.ts";

export interface ExportDocument {
  version: number;
  project: string;
  generatedAt: number;
  jobs: JobBundle[];
  digest: string;
}

export class ExportService {
  private readonly snapshots = new ExportSnapshots();

  constructor(
    private readonly db: Database,
    private readonly jobs: JobRepository,
    private readonly evidence: EvidenceRepository,
    private readonly events: EventRepository,
    private readonly attempts: AttemptRepository,
    private readonly access: AccessService,
    private readonly config: Config,
    private readonly now: () => number,
  ) {}

  bundle(actor: Principal, jobId: string): JobBundle {
    this.access.require(actor, "case_read");
    return this.db.transaction(() => {
      const job = this.snapshots.read(this.jobs.require(jobId));
      this.access.requireJob(actor, "case_read", job);
      return {
        job,
        evidence: this.evidence.list(jobId),
        events: this.events.all(jobId),
        attempts: this.attempts.list(jobId),
      };
    })();
  }

  project(actor: Principal, includeArchived = false): ExportDocument {
    this.access.require(actor, "case_read");
    return this.db.transaction(() => {
      const result = this.jobs.list({
        project: actor.project,
        archived: includeArchived ? undefined : false,
        limit: this.config.maxExportJobs,
        offset: 0,
      });
      if (result.total > this.config.maxExportJobs) limitExceeded("export exceeds configured job count");
      const bundles = result.items.map(job => this.bundle(actor, job.id));
      const generatedAt = this.now();
      const data = {
        version: 1,
        project: actor.project,
        generatedAt,
        jobs: bundles,
      };
      return { ...data, digest: checksum(JSON.stringify(data)) };
    })();
  }

  verify(document: ExportDocument): boolean {
    const { digest, ...data } = document;
    if (data.version !== 1) return false;
    if (!matchesChecksum(JSON.stringify(data), digest)) return false;
    return data.jobs.every(bundle =>
      bundle.job.project === data.project &&
      bundle.evidence.every(item =>
        item.jobId === bundle.job.id && matchesChecksum(item.content, item.checksum),
      ) &&
      bundle.events.every(event => event.jobId === bundle.job.id) &&
      bundle.attempts.every(attempt => attempt.jobId === bundle.job.id),
    );
  }

  csv(actor: Principal): string {
    const document = this.project(actor);
    const fields = ["id", "title", "stage", "owner", "priority", "revision"] as const;
    const quote = (value: unknown): string => {
      let text = String(value);
      // Neutralize spreadsheet formulas when exported text is opened by a spreadsheet.
      if (/^[=+@-]/.test(text)) text = `'${text}`;
      return `"${text.replaceAll('"', '""')}"`;
    };
    const rows = [fields.map(quote).join(",")];
    for (const { job } of document.jobs) rows.push(fields.map(field => quote(job[field])).join(","));
    return rows.join("\r\n") + "\r\n";
  }

  requireVerified(document: ExportDocument): void {
    if (!this.verify(document)) conflict("export failed integrity validation");
  }
}
