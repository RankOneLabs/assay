import type { Database, SQLQueryBindings } from "bun:sqlite";
import type { Page } from "../domain/models.ts";
import type { JobTag, TagCount } from "../domain/tags.ts";
import type { SearchQuery } from "../domain/search_query.ts";
import { page } from "./paging.ts";

function placeholders(values: readonly unknown[]): string {
  return values.map(() => "?").join(", ");
}

/** Tags belong to a job row; project scope always comes from the job. */
export class TagRepository {
  constructor(private readonly db: Database) {}

  forJob(jobId: string): JobTag[] {
    return this.db.query<JobTag, [string]>(`
      SELECT tag, added_by AS addedBy, created_at AS createdAt
      FROM job_tags WHERE job_id = ? ORDER BY tag
    `).all(jobId);
  }

  add(jobId: string, tag: string, actor: string, now: number): void {
    this.db.query(`
      INSERT OR IGNORE INTO job_tags (job_id, tag, added_by, created_at) VALUES (?, ?, ?, ?)
    `).run(jobId, tag, actor, now);
  }

  remove(jobId: string, tags: readonly string[]): number {
    return this.db.query(`
      DELETE FROM job_tags WHERE job_id = ? AND tag IN (${placeholders(tags)})
    `).run(jobId, ...tags).changes;
  }

  /** Ids of the project's jobs carrying any of the tags. */
  holders(project: string, tags: readonly string[]): string[] {
    return this.db.query<{ id: string }, SQLQueryBindings[]>(`
      SELECT DISTINCT t.job_id AS id FROM job_tags t JOIN jobs j ON j.id = t.job_id
      WHERE j.project = ? AND t.tag IN (${placeholders(tags)}) ORDER BY t.job_id
    `).all(project, ...tags).map(row => row.id);
  }

  counts(project: string, limit: number, offset: number): Page<TagCount> {
    const total = this.db.query<{ count: number }, [string]>(`
      SELECT COUNT(DISTINCT t.tag) AS count FROM job_tags t JOIN jobs j ON j.id = t.job_id WHERE j.project = ?
    `).get(project)!.count;
    const rows = this.db.query<TagCount, [string, number, number]>(`
      SELECT t.tag, COUNT(*) AS jobs, SUM(CASE WHEN j.archived_at IS NULL THEN 0 ELSE 1 END) AS archived
      FROM job_tags t JOIN jobs j ON j.id = t.job_id WHERE j.project = ?
      GROUP BY t.tag ORDER BY jobs DESC, t.tag ASC LIMIT ? OFFSET ?
    `).all(project, limit, offset);
    return page(rows, total, limit, offset);
  }

  /** Ids of matching jobs in the job listing's order: priority, then age, then id. */
  search(project: string, query: SearchQuery, limit: number, offset: number): Page<string> {
    const conditions = ["j.project = ?", query.archived ? "j.archived_at IS NOT NULL" : "j.archived_at IS NULL"];
    const bindings: SQLQueryBindings[] = [project];
    for (const tag of query.tags) {
      conditions.push("EXISTS (SELECT 1 FROM job_tags t WHERE t.job_id = j.id AND t.tag = ?)");
      bindings.push(tag);
    }
    const filters: [string, SQLQueryBindings | undefined][] = [
      ["j.owner = ?", query.owner],
      ["j.stage = ?", query.stage],
      ["j.priority >= ?", query.minPriority],
      ["j.priority <= ?", query.maxPriority],
    ];
    for (const [condition, value] of filters) {
      if (value === undefined) continue;
      conditions.push(condition);
      bindings.push(value);
    }
    if (query.text !== undefined) {
      const escaped = `%${query.text.replace(/[\\%_]/g, match => `\\${match}`)}%`;
      conditions.push("(j.title LIKE ? ESCAPE '\\' OR j.description LIKE ? ESCAPE '\\')");
      bindings.push(escaped, escaped);
    }
    const where = conditions.join(" AND ");
    const total = this.db.query<{ count: number }, SQLQueryBindings[]>(
      `SELECT COUNT(*) AS count FROM jobs j WHERE ${where}`,
    ).get(...bindings)!.count;
    const ids = this.db.query<{ id: string }, SQLQueryBindings[]>(`
      SELECT j.id FROM jobs j WHERE ${where}
      ORDER BY j.priority DESC, j.created_at ASC, j.id ASC LIMIT ? OFFSET ?
    `).all(...bindings, limit, offset).map(row => row.id);
    return page(ids, total, limit, offset);
  }
}
