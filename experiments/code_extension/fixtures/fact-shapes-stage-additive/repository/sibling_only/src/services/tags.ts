import type { Database } from "bun:sqlite";
import type { Page, Principal } from "../domain/models.ts";
import { readAccess } from "../domain/access_levels.ts";
import { conflict, limitExceeded, missing } from "../domain/errors.ts";
import {
  addTagsSchema, mergeTagsSchema, renameTagSchema, tagSchema, maxTagsPerJob,
  type JobTag, type TagCount,
} from "../domain/tags.ts";
import { TagRepository } from "../repositories/tags.ts";
import { JobRepository } from "../repositories/jobs.ts";
import { EventRepository } from "../repositories/events.ts";
import { AccessService } from "./access.ts";
import { JobService } from "./jobs.ts";

export class TagService {
  constructor(
    private readonly db: Database,
    private readonly tags: TagRepository,
    private readonly jobs: JobRepository,
    private readonly jobService: JobService,
    private readonly events: EventRepository,
    private readonly access: AccessService,
    private readonly now: () => number,
  ) {}

  list(actor: Principal, jobId: string): JobTag[] {
    this.jobService.get(actor, jobId);
    return this.tags.forJob(jobId);
  }

  /** Adding a tag the job already carries is not an error; only new tags are recorded. */
  add(actor: Principal, jobId: string, input: unknown): { added: string[]; tags: JobTag[] } {
    this.access.require(actor, "case_write");
    const requested = [...new Set(addTagsSchema.parse(input).tags)];
    return this.db.transaction(() => {
      this.requireTaggable(actor, jobId);
      const existing = new Set(this.tags.forJob(jobId).map(item => item.tag));
      const added = requested.filter(tag => !existing.has(tag));
      if (existing.size + added.length > maxTagsPerJob) {
        limitExceeded(`a job carries at most ${maxTagsPerJob} tags`);
      }
      const now = this.now();
      for (const tag of added) this.tags.add(jobId, tag, actor.id, now);
      if (added.length) this.events.append(jobId, "job.tagged", actor.id, { tags: added }, now);
      return { added, tags: this.tags.forJob(jobId) };
    })();
  }

  remove(actor: Principal, jobId: string, input: unknown): JobTag[] {
    this.access.require(actor, "case_write");
    const tag = tagSchema.parse(input);
    return this.db.transaction(() => {
      this.requireTaggable(actor, jobId);
      if (!this.tags.remove(jobId, [tag])) missing("tag", tag);
      this.events.append(jobId, "job.untagged", actor.id, { tag }, this.now());
      return this.tags.forJob(jobId);
    })();
  }

  /** Every tag in use in the project, most used first, with how many tagged jobs are archived. */
  project(actor: Principal, limit: number, offset: number): Page<TagCount> {
    this.access.require(actor, readAccess);
    return this.tags.counts(actor.project, limit, offset);
  }

  /** Rename a tag on every job of the project; an existing target requires a merge instead. */
  rename(actor: Principal, input: unknown): { target: string; jobs: string[] } {
    this.access.require(actor, "case_admin");
    const parsed = renameTagSchema.parse(input);
    return this.db.transaction(() => {
      if (this.tags.holders(actor.project, [parsed.to]).length) {
        conflict("target tag is already in use; merge the tags instead", { tag: parsed.to });
      }
      return this.retag(actor, [parsed.from], parsed.to, "job.tag_renamed");
    })();
  }

  merge(actor: Principal, input: unknown): { target: string; jobs: string[] } {
    this.access.require(actor, "case_admin");
    const parsed = mergeTagsSchema.parse(input);
    return this.db.transaction(() => this.retag(actor, parsed.sources, parsed.target, "job.tags_merged"))();
  }

  /** Replace source tags with the target on every job in the project, archived jobs included. */
  private retag(actor: Principal, sources: readonly string[], target: string, action: string) {
    const jobs = this.tags.holders(actor.project, sources);
    if (!jobs.length) missing("tag", sources.join(", "));
    const now = this.now();
    for (const jobId of jobs) {
      this.tags.remove(jobId, sources);
      this.tags.add(jobId, target, actor.id, now);
      this.events.append(jobId, action, actor.id, { sources, target }, now);
    }
    return { target, jobs };
  }

  private requireTaggable(actor: Principal, jobId: string): void {
    const job = this.jobs.require(jobId);
    this.access.requireJob(actor, "case_write", job);
    if (job.archivedAt !== null) conflict("archived job is read only");
  }
}
