import type { Database } from "bun:sqlite";
import { z } from "zod";
import type { Principal, Job } from "../domain/models.ts";
import type { Config } from "../config.ts";
import { createJobSchema, evidenceSchema, keySchema } from "../domain/validation.ts";
import { conflict, forbidden, limitExceeded } from "../domain/errors.ts";
import { checksum } from "../domain/checksum.ts";
import { JobService } from "./jobs.ts";
import { EvidenceService } from "./evidence.ts";
import { AccessService } from "./access.ts";
import { JobRepository } from "../repositories/jobs.ts";
import { EvidenceRepository } from "../repositories/evidence.ts";

const importEntrySchema = z.object({
  job: createJobSchema,
  evidence: z.array(evidenceSchema).max(1000).default([]),
}).strict();

const importSchema = z.object({
  version: z.literal(1),
  entries: z.array(importEntrySchema).min(1).max(100),
}).strict();

export interface ImportIssue {
  entry: number;
  id: string;
  message: string;
}

export interface ImportPreview {
  jobs: number;
  evidence: number;
  issues: ImportIssue[];
  digest: string;
}

/** Imports use the same public operations as individual requests within one transaction. */
export class ImportService {
  constructor(
    private readonly db: Database,
    private readonly jobs: JobService,
    private readonly evidence: EvidenceService,
    private readonly access: AccessService,
    private readonly jobRepository: JobRepository,
    private readonly evidenceRepository: EvidenceRepository,
    private readonly config: Config,
  ) {}

  preview(actor: Principal, input: unknown): ImportPreview {
    this.access.require(actor, "case_write");
    const parsed = importSchema.parse(input);
    const issues: ImportIssue[] = [];
    if (parsed.entries.length > this.config.maxBulkJobs) limitExceeded("import job limit reached");
    const seenJobs = new Set<string>();
    const seenEvidence = new Set<string>();
    let evidenceCount = 0;
    for (const [index, entry] of parsed.entries.entries()) {
      const id = entry.job.id;
      if (entry.job.project !== actor.project) forbidden("import project mismatch");
      if (seenJobs.has(id) || this.jobRepository.get(id)) {
        issues.push({ entry: index, id, message: "job id already exists" });
      }
      seenJobs.add(id);
      if (entry.evidence.length > this.config.maxEvidence) {
        issues.push({ entry: index, id, message: "evidence count limit reached" });
      }
      const digests = new Set<string>();
      for (const item of entry.evidence) {
        evidenceCount++;
        if (seenEvidence.has(item.id) || this.evidenceRepository.get(item.id)) {
          issues.push({ entry: index, id: item.id, message: "evidence id already exists" });
        }
        seenEvidence.add(item.id);
        const digest = checksum(item.content);
        if (digests.has(digest)) {
          issues.push({ entry: index, id: item.id, message: "duplicate evidence content in job" });
        }
        digests.add(digest);
        if (new TextEncoder().encode(item.content).byteLength > this.config.maxEvidenceBytes) {
          issues.push({ entry: index, id: item.id, message: "evidence byte limit exceeded" });
        }
      }
    }
    if (this.jobRepository.count(actor.project) + parsed.entries.length > this.config.maxJobs) {
      issues.push({ entry: -1, id: actor.project, message: "project job limit reached" });
    }
    return {
      jobs: parsed.entries.length,
      evidence: evidenceCount,
      issues,
      digest: checksum(JSON.stringify(parsed)),
    };
  }

  commit(actor: Principal, input: unknown, expectedDigest: string): Job[] {
    keySchema.parse(actor.id);
    return this.db.transaction(() => {
      const preview = this.preview(actor, input);
      if (preview.digest !== expectedDigest) conflict("import changed since preview");
      if (preview.issues.length) conflict("import preview has issues", { issues: preview.issues });
      const parsed = importSchema.parse(input);
      const created: Job[] = [];
      for (const entry of parsed.entries) {
        const job = this.jobs.create(actor, entry.job);
        for (const item of entry.evidence) this.evidence.attach(actor, job.id, item);
        created.push(job);
      }
      return created;
    })();
  }

  /** A validation-only preview performs no INSERT, DELETE or UPDATE. */
  validate(actor: Principal, input: unknown): boolean {
    return this.preview(actor, input).issues.length === 0;
  }
}
