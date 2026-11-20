import type { Database, SQLQueryBindings } from "bun:sqlite";
import type { Page, Principal } from "../domain/models.ts";
import type { Comment, CommentVersion, Mention, MentionFilter } from "../domain/comments.ts";
import { conflict, missing, revisionMatches } from "../domain/errors.ts";

interface CommentRow {
  id: string;
  job_id: string;
  parent_id: string | null;
  depth: number;
  author: string;
  body: string;
  revision: number;
  created_at: number;
  updated_at: number;
  deleted_at: number | null;
  deleted_by: string | null;
}

interface MentionRow {
  comment_id: string;
  job_id: string;
  job_title: string;
  author: string;
  body: string;
  created_at: number;
  read_at: number | null;
}

export interface CommentCreate {
  id: string;
  parentId: string | null;
  depth: number;
  author: string;
  body: string;
}

export class CommentRepository {
  constructor(private readonly db: Database) {}

  get(id: string): Comment | null {
    const row = this.db.query<CommentRow, [string]>("SELECT * FROM job_comments WHERE id = ?").get(id);
    return row ? this.decode(row) : null;
  }

  require(id: string): Comment {
    return this.get(id) ?? missing("comment", id);
  }

  list(jobId: string): Comment[] {
    return this.db.query<CommentRow, [string]>(
      "SELECT * FROM job_comments WHERE job_id = ? ORDER BY created_at ASC, id ASC",
    ).all(jobId).map(row => this.decode(row));
  }

  count(jobId: string): number {
    return this.db.query<{ count: number }, [string]>(
      "SELECT COUNT(*) AS count FROM job_comments WHERE job_id = ?",
    ).get(jobId)!.count;
  }

  create(jobId: string, project: string, input: CommentCreate, mentions: readonly string[], now: number): Comment {
    if (this.get(input.id)) conflict("comment id already exists");
    this.db.query(`
      INSERT INTO job_comments (
        id, job_id, parent_id, depth, author, body, revision, created_at, updated_at, deleted_at, deleted_by
      ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, NULL, NULL)
    `).run(input.id, jobId, input.parentId, input.depth, input.author, input.body, now, now);
    this.syncMentions(input.id, project, mentions, now);
    return this.require(input.id);
  }

  /** Keep the replaced body as history, then store the new one under the next revision. */
  edit(
    current: Comment, project: string, body: string,
    expectedRevision: number, mentions: readonly string[], now: number,
  ): Comment {
    revisionMatches(current.revision, expectedRevision);
    this.db.query(`
      INSERT INTO job_comment_revisions (comment_id, revision, body, created_at) VALUES (?, ?, ?, ?)
    `).run(current.id, current.revision, current.body, current.updatedAt);
    this.db.query(`
      UPDATE job_comments SET body = ?, revision = revision + 1, updated_at = ?
      WHERE id = ? AND revision = ?
    `).run(body, now, current.id, expectedRevision);
    this.syncMentions(current.id, project, mentions, now);
    return this.require(current.id);
  }

  /** Deleted comments keep their place in the thread but none of their text or mentions. */
  softDelete(current: Comment, actor: string, expectedRevision: number, now: number): Comment {
    revisionMatches(current.revision, expectedRevision);
    this.db.query(`
      UPDATE job_comments SET body = '', deleted_at = ?, deleted_by = ?, revision = revision + 1, updated_at = ?
      WHERE id = ? AND revision = ?
    `).run(now, actor, now, current.id, expectedRevision);
    this.db.query("DELETE FROM job_comment_revisions WHERE comment_id = ?").run(current.id);
    this.db.query("DELETE FROM comment_mentions WHERE comment_id = ?").run(current.id);
    return this.require(current.id);
  }

  versions(id: string): CommentVersion[] {
    return this.db.query<CommentVersion, [string]>(`
      SELECT revision, body, created_at AS createdAt FROM job_comment_revisions
      WHERE comment_id = ? ORDER BY revision ASC
    `).all(id);
  }

  mentions(principal: Principal, filter: MentionFilter): Page<Mention> {
    const conditions = ["m.project = ?", "m.principal = ?"];
    const bindings: SQLQueryBindings[] = [principal.project, principal.id];
    if (filter.unread !== undefined) conditions.push(filter.unread ? "m.read_at IS NULL" : "m.read_at IS NOT NULL");
    if (filter.jobId !== undefined) {
      conditions.push("c.job_id = ?");
      bindings.push(filter.jobId);
    }
    const from = `
      FROM comment_mentions m
      JOIN job_comments c ON c.id = m.comment_id
      JOIN jobs j ON j.id = c.job_id AND j.project = m.project
      WHERE ${conditions.join(" AND ")}
    `;
    const total = this.db.query<{ count: number }, SQLQueryBindings[]>(`SELECT COUNT(*) AS count ${from}`)
      .get(...bindings)!.count;
    const rows = this.db.query<MentionRow, SQLQueryBindings[]>(`
      SELECT m.comment_id, c.job_id, j.title AS job_title, c.author, c.body, m.created_at, m.read_at
      ${from} ORDER BY m.created_at DESC, m.comment_id ASC LIMIT ? OFFSET ?
    `).all(...bindings, filter.limit, filter.offset);
    return {
      items: rows.map(row => ({
        commentId: row.comment_id,
        jobId: row.job_id,
        jobTitle: row.job_title,
        author: row.author,
        body: row.body,
        createdAt: row.created_at,
        readAt: row.read_at,
      })),
      total,
      limit: filter.limit,
      offset: filter.offset,
      nextOffset: filter.offset + rows.length < total ? filter.offset + rows.length : null,
    };
  }

  unreadCount(principal: Principal): number {
    return this.db.query<{ count: number }, [string, string]>(`
      SELECT COUNT(*) AS count FROM comment_mentions WHERE project = ? AND principal = ? AND read_at IS NULL
    `).get(principal.project, principal.id)!.count;
  }

  /** Set or clear the read marker on the given mentions; returns how many markers changed. */
  mark(principal: Principal, commentIds: readonly string[], readAt: number | null): number {
    let changed = 0;
    for (const id of commentIds) {
      changed += this.db.query(`
        UPDATE comment_mentions SET read_at = ?
        WHERE project = ? AND principal = ? AND comment_id = ? AND (read_at IS NULL) = ?
      `).run(readAt, principal.project, principal.id, id, readAt === null ? 0 : 1).changes;
    }
    return changed;
  }

  markAllRead(principal: Principal, now: number): number {
    return this.db.query(`
      UPDATE comment_mentions SET read_at = ? WHERE project = ? AND principal = ? AND read_at IS NULL
    `).run(now, principal.project, principal.id).changes;
  }

  /** Mentions that survive an edit keep their read marker; new ones arrive unread. */
  private syncMentions(commentId: string, project: string, names: readonly string[], now: number): void {
    for (const existing of this.mentionNames(commentId)) {
      if (!names.includes(existing)) {
        this.db.query("DELETE FROM comment_mentions WHERE comment_id = ? AND principal = ?").run(commentId, existing);
      }
    }
    for (const name of names) {
      this.db.query(`
        INSERT OR IGNORE INTO comment_mentions (comment_id, principal, project, created_at, read_at)
        VALUES (?, ?, ?, ?, NULL)
      `).run(commentId, name, project, now);
    }
  }

  private mentionNames(commentId: string): string[] {
    return this.db.query<{ principal: string }, [string]>(
      "SELECT principal FROM comment_mentions WHERE comment_id = ? ORDER BY principal ASC",
    ).all(commentId).map(row => row.principal);
  }

  private decode(row: CommentRow): Comment {
    return {
      id: row.id,
      jobId: row.job_id,
      parentId: row.parent_id,
      depth: row.depth,
      author: row.author,
      body: row.body,
      mentions: this.mentionNames(row.id),
      revision: row.revision,
      createdAt: row.created_at,
      updatedAt: row.updated_at,
      deletedAt: row.deleted_at,
      deletedBy: row.deleted_by,
    };
  }
}
