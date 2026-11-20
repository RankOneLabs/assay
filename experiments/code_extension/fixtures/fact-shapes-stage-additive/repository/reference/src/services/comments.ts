import type { Database } from "bun:sqlite";
import type { Job, Page, Principal } from "../domain/models.ts";
import type { Comment, CommentNode, CommentVersion, Mention } from "../domain/comments.ts";
import {
  addCommentSchema, editCommentSchema, mentionFilterSchema, markMentionsSchema,
  parseMentions, buildThread, maxCommentsPerJob, maxReplyDepth,
} from "../domain/comments.ts";
import { revisionSchema } from "../domain/validation.ts";
import { readAccess } from "../domain/access_levels.ts";
import { conflict, forbidden, invalid, limitExceeded, missing } from "../domain/errors.ts";
import { CommentRepository } from "../repositories/comments.ts";
import { JobRepository } from "../repositories/jobs.ts";
import { EventRepository } from "../repositories/events.ts";
import { GrantRepository } from "../repositories/grants.ts";
import { AccessService } from "./access.ts";
import { JobService } from "./jobs.ts";

/** Discussion on a job: threaded comments, their edit history, and per-principal mentions. */
export class CommentService {
  constructor(
    private readonly db: Database,
    private readonly comments: CommentRepository,
    private readonly jobs: JobRepository,
    private readonly events: EventRepository,
    private readonly grants: GrantRepository,
    private readonly access: AccessService,
    private readonly jobService: JobService,
    private readonly now: () => number,
  ) {}

  add(actor: Principal, jobId: string, input: unknown): Comment {
    this.access.require(actor, "case_write");
    const parsed = addCommentSchema.parse(input);
    const mentions = parseMentions(parsed.body, actor.id);
    return this.db.transaction(() => {
      const job = this.writableJob(actor, jobId);
      if (this.comments.count(jobId) >= maxCommentsPerJob) limitExceeded("job comment limit reached");
      const parent = parsed.parentId === undefined ? null : this.inJob(jobId, parsed.parentId);
      if (parent !== null && parent.deletedAt !== null) conflict("cannot reply to a deleted comment");
      const depth = parent === null ? 0 : parent.depth + 1;
      if (depth > maxReplyDepth) conflict("reply nesting limit reached", { maxReplyDepth });
      const now = this.now();
      const comment = this.comments.create(jobId, job.project, {
        id: parsed.id,
        parentId: parent?.id ?? null,
        depth,
        author: actor.id,
        body: parsed.body,
      }, mentions, now);
      this.events.append(jobId, "comment.added", actor.id, {
        id: comment.id,
        parentId: comment.parentId,
        mentions,
      }, now);
      return comment;
    })();
  }

  thread(actor: Principal, jobId: string): { jobId: string; total: number; deleted: number; comments: CommentNode[] } {
    this.jobService.get(actor, jobId);
    const all = this.comments.list(jobId);
    return {
      jobId,
      total: all.length,
      deleted: all.filter(comment => comment.deletedAt !== null).length,
      comments: buildThread(all),
    };
  }

  get(actor: Principal, jobId: string, id: string): Comment {
    this.jobService.get(actor, jobId);
    return this.inJob(jobId, id);
  }

  edit(actor: Principal, jobId: string, id: string, input: unknown): Comment {
    this.access.require(actor, "case_write");
    const parsed = editCommentSchema.parse(input);
    const mentions = parseMentions(parsed.body, actor.id);
    return this.db.transaction(() => {
      const job = this.writableJob(actor, jobId);
      const current = this.inJob(jobId, id);
      if (current.deletedAt !== null) conflict("deleted comments cannot be edited");
      if (current.author !== actor.id) forbidden("only the author can edit a comment");
      if (current.body === parsed.body) invalid("edit does not change the comment");
      const now = this.now();
      const comment = this.comments.edit(current, job.project, parsed.body, parsed.expectedRevision, mentions, now);
      this.events.append(jobId, "comment.edited", actor.id, {
        id,
        revision: comment.revision,
        mentions: mentions.filter(name => !current.mentions.includes(name)),
      }, now);
      return comment;
    })();
  }

  /** Every body the comment has held, oldest first, ending with the current one. */
  history(actor: Principal, jobId: string, id: string): { id: string; deleted: boolean; versions: CommentVersion[] } {
    const comment = this.get(actor, jobId, id);
    if (comment.deletedAt !== null) return { id, deleted: true, versions: [] };
    return {
      id,
      deleted: false,
      versions: [
        ...this.comments.versions(id),
        { revision: comment.revision, body: comment.body, createdAt: comment.updatedAt },
      ],
    };
  }

  remove(actor: Principal, jobId: string, id: string, input: unknown): Comment {
    this.access.require(actor, "case_write");
    const parsed = revisionSchema.parse(input);
    return this.db.transaction(() => {
      this.writableJob(actor, jobId);
      const current = this.inJob(jobId, id);
      if (current.deletedAt !== null) conflict("comment already deleted");
      const moderated = current.author !== actor.id;
      if (moderated && !this.grants.has(actor, "case_admin")) {
        forbidden("only the author or a project administrator can delete a comment");
      }
      const now = this.now();
      const comment = this.comments.softDelete(current, actor.id, parsed.expectedRevision, now);
      this.events.append(jobId, "comment.deleted", actor.id, { id, author: current.author, moderated }, now);
      return comment;
    })();
  }

  mentions(actor: Principal, query: unknown): Page<Mention> & { unread: number } {
    this.access.require(actor, readAccess);
    const filter = mentionFilterSchema.parse(query);
    return { ...this.comments.mentions(actor, filter), unread: this.comments.unreadCount(actor) };
  }

  markMentions(actor: Principal, input: unknown): { changed: number; unread: number } {
    this.access.require(actor, readAccess);
    const parsed = markMentionsSchema.parse(input);
    return this.db.transaction(() => ({
      changed: this.comments.mark(actor, parsed.commentIds, parsed.read ? this.now() : null),
      unread: this.comments.unreadCount(actor),
    }))();
  }

  markAllRead(actor: Principal): { changed: number; unread: number } {
    this.access.require(actor, readAccess);
    return { changed: this.comments.markAllRead(actor, this.now()), unread: 0 };
  }

  /** Comments are only written on live jobs: never archived, never in the completed stage. */
  private writableJob(actor: Principal, jobId: string): Job {
    const job = this.jobs.require(jobId);
    this.access.requireJob(actor, "case_write", job);
    this.jobService.requireMutable(job);
    return job;
  }

  private inJob(jobId: string, id: string): Comment {
    const comment = this.comments.require(id);
    if (comment.jobId !== jobId) missing("comment", id);
    return comment;
  }
}
