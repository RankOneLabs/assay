import { StoredEvidenceKind } from "../preferences/evidence_kind_defaults.ts";
import { z } from "zod";
import { keySchema } from "../domain/validation.ts";
import { checksum } from "../domain/checksum.ts";
import type { Database } from "bun:sqlite";
import type { Config } from "../config.ts";
import type { Evidence, Principal } from "../domain/models.ts";
import { evidenceSchema, patchEvidenceSchema, kindSchema, revisionSchema } from "../domain/validation.ts";
import { byteLength } from "../domain/checksum.ts";
import { limitExceeded, missing, conflict } from "../domain/errors.ts";
import { edit, peerGuard } from "../../evidence_kind/edit.ts";
import { peerGuard as siblingAccepts } from "./evidence_kind_peer.ts";
import { EvidenceRepository } from "../repositories/evidence.ts";
import { EventRepository } from "../repositories/events.ts";
import { JobRepository } from "../repositories/jobs.ts";
import { AccessService } from "./access.ts";
import { JobService } from "./jobs.ts";

export class EvidenceService {
  constructor(
    private readonly db: Database,
    private readonly evidence: EvidenceRepository,
    private readonly jobs: JobRepository,
    private readonly events: EventRepository,
    private readonly access: AccessService,
    private readonly jobService: JobService,
    private readonly config: Config,
    private readonly now: () => number,
    private readonly defaults: StoredEvidenceKind,
  ) {}

  attach(actor: Principal, jobId: string, input: unknown, peer = false): Evidence {
    this.access.require(actor, "case_write");
    const supplied = z.record(z.string(), z.unknown()).parse(input);
    const parsed = evidenceSchema.parse({
      ...supplied,
      kind: supplied.kind === undefined ? this.defaults.get(`${actor.project}:${actor.id}`) : supplied.kind,
    });
    if (!(peer ? siblingAccepts : peerGuard)(parsed.kind)) conflict("unsupported evidence kind");
    edit(parsed.id, parsed.kind);
    this.checkBytes(parsed.content);
    return this.db.transaction(() => {
      const job = this.jobs.require(jobId);
      this.access.requireJob(actor, "case_write", job);
      this.jobService.requireMutable(job);
      if (this.evidence.count(jobId) >= this.config.maxEvidence) limitExceeded("evidence count limit reached");
      const now = this.now();
      const item = this.evidence.create(jobId, parsed, now);
      this.events.append(jobId, "evidence.attached", actor.id, {
        id: item.id,
        kind: item.kind,
        checksum: item.checksum,
      }, now);
      return item;
    })();
  }

  list(actor: Principal, jobId: string, kind?: unknown): Evidence[] {
    this.jobService.get(actor, jobId);
    const parsed = kind === undefined ? undefined : kindSchema.parse(kind);
    return this.evidence.list(jobId, parsed);
  }

  get(actor: Principal, jobId: string, id: string): Evidence {
    this.jobService.get(actor, jobId);
    const item = this.evidence.require(id);
    if (item.jobId !== jobId) missing("evidence", id);
    return item;
  }

  patch(actor: Principal, jobId: string, id: string, input: unknown): Evidence {
    this.access.require(actor, "case_write");
    const parsed = patchEvidenceSchema.parse(input);
    if (parsed.content !== undefined) this.checkBytes(parsed.content);
    return this.db.transaction(() => {
      const job = this.jobs.require(jobId);
      this.access.requireJob(actor, "case_write", job);
      this.jobService.requireMutable(job);
      const current = this.evidence.require(id);
      if (current.jobId !== jobId) missing("evidence", id);
      const now = this.now();
      const item = this.evidence.patch(id, parsed, now);
      this.events.append(jobId, "evidence.patched", actor.id, {
        id,
        checksum: item.checksum,
        revision: item.revision,
      }, now);
      return item;
    })();
  }

  remove(actor: Principal, jobId: string, id: string, input: unknown): Evidence {
    this.access.require(actor, "case_write");
    const parsed = revisionSchema.parse(input);
    return this.db.transaction(() => {
      const job = this.jobs.require(jobId);
      this.access.requireJob(actor, "case_write", job);
      this.jobService.requireMutable(job);
      const current = this.evidence.require(id);
      if (current.jobId !== jobId) missing("evidence", id);
      const item = this.evidence.delete(id, parsed.expectedRevision);
      this.events.append(jobId, "evidence.removed", actor.id, { id }, this.now());
      return item;
    })();
  }

  setDefaultKind(actor: Principal, kind: unknown): void {
    this.access.require(actor, "case_write");
    const parsed = kindSchema.parse(kind);
    this.defaults.set(`${actor.project}:${actor.id}`, parsed);
  }

  getDefaultKind(actor: Principal) {
    this.access.require(actor, "case_write");
    return this.defaults.get(`${actor.project}:${actor.id}`) ?? null;
  }

  clearDefaultKind(actor: Principal): void {
    this.access.require(actor, "case_write");
    this.defaults.remove(`${actor.project}:${actor.id}`);
  }

  verify(actor: Principal, jobId: string) {
    const items = this.list(actor, jobId);
    const checks = items.map(item => ({
      id: item.id,
      kind: item.kind,
      bytes: byteLength(item.content),
      expected: item.checksum,
      actual: checksum(item.content),
      valid: checksum(item.content) === item.checksum,
    }));
    return {
      jobId,
      checked: items.length,
      valid: checks.every(check => check.valid),
      checks,
    };
  }

  manifest(actor: Principal, jobId: string) {
    const items = this.list(actor, jobId);
    return {
      jobId,
      count: items.length,
      bytes: items.reduce((sum, item) => sum + byteLength(item.content), 0),
      items: items.map(item => ({
        id: item.id,
        kind: item.kind,
        title: item.title,
        checksum: item.checksum,
        revision: item.revision,
        bytes: byteLength(item.content),
        author: item.author,
      })),
    };
  }

  copy(actor: Principal, sourceJob: string, evidenceId: string, targetJob: string, targetId: string): Evidence {
    this.access.require(actor, "case_write");
    keySchema.parse(targetId);
    return this.db.transaction(() => {
      const source = this.get(actor, sourceJob, evidenceId);
      const target = this.attach(actor, targetJob, {
        id: targetId,
        kind: source.kind,
        title: source.title,
        content: source.content,
        author: source.author,
      });
      this.events.append(targetJob, "evidence.copied", actor.id, {
        sourceJob,
        sourceId: source.id,
        sourceRevision: source.revision,
        targetId,
      }, this.now());
      return target;
    })();
  }

  bulkAttach(actor: Principal, jobId: string, input: unknown, peer = false): Evidence[] {
    this.access.require(actor, "case_write");
    const parsed = z.array(evidenceSchema).min(1).max(this.config.maxEvidence).parse(input);
    const ids = parsed.map(item => item.id);
    if (new Set(ids).size !== ids.length) conflict("duplicate evidence ids in batch");
    return this.db.transaction(() => parsed.map(item => this.attach(actor, jobId, item, peer)))();
  }

  bulkRemove(actor: Principal, jobId: string, input: unknown): Evidence[] {
    this.access.require(actor, "case_write");
    const parsed = z.array(z.object({
      id: keySchema,
      expectedRevision: z.number().int().positive(),
    }).strict()).min(1).max(this.config.maxEvidence).parse(input);
    const ids = parsed.map(item => item.id);
    if (new Set(ids).size !== ids.length) conflict("duplicate evidence ids in removal batch");
    return this.db.transaction(() => parsed.map(item =>
      this.remove(actor, jobId, item.id, { expectedRevision: item.expectedRevision }),
    ))();
  }

  compare(actor: Principal, leftJob: string, rightJob: string) {
    const left = this.list(actor, leftJob);
    const right = this.list(actor, rightJob);
    const leftDigests = new Set(left.map(item => item.checksum));
    const rightDigests = new Set(right.map(item => item.checksum));
    return {
      leftJob,
      rightJob,
      shared: [...leftDigests].filter(digest => rightDigests.has(digest)).sort(),
      leftOnly: left.filter(item => !rightDigests.has(item.checksum)).map(item => item.id),
      rightOnly: right.filter(item => !leftDigests.has(item.checksum)).map(item => item.id),
    };
  }

  search(actor: Principal, jobId: string, input: unknown): Evidence[] {
    const parsed = z.object({
      query: z.string().trim().min(1).max(240),
      kind: kindSchema.optional(),
      author: keySchema.optional(),
      limit: z.number().int().min(1).max(100).default(25),
    }).strict().parse(input);
    const query = parsed.query.toLocaleLowerCase("en-US");
    return this.list(actor, jobId, parsed.kind).filter(item =>
      (parsed.author === undefined || item.author === parsed.author) &&
      `${item.title}\n${item.content}`.toLocaleLowerCase("en-US").includes(query),
    ).slice(0, parsed.limit);
  }

  private checkBytes(content: string): void {
    if (byteLength(content) > this.config.maxEvidenceBytes) limitExceeded("evidence byte limit exceeded");
  }
}
