import type { Database, SQLQueryBindings } from "bun:sqlite";
import type { Stage } from "../../stage/types.ts";
import type { Job, JobCreate, JobFilter, JobPatch, Page } from "../domain/models.ts";
import { missing, revisionMatches, conflict } from "../domain/errors.ts";

interface JobRow {
  id: string;
  title: string;
  description: string;
  stage: Stage;
  priority: number;
  owner: string;
  project: string;
  revision: number;
  created_at: number;
  updated_at: number;
  archived_at: number | null;
}

function decode(row: JobRow): Job {
  return {
    id: row.id,
    title: row.title,
    description: row.description,
    stage: row.stage,
    priority: row.priority,
    owner: row.owner,
    project: row.project,
    revision: row.revision,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    archivedAt: row.archived_at,
  };
}

export class JobRepository {
  constructor(private readonly db: Database) {}

  get(id: string): Job | null {
    const row = this.db.query<JobRow, [string]>("SELECT * FROM jobs WHERE id = ?").get(id);
    return row ? decode(row) : null;
  }

  require(id: string): Job {
    return this.get(id) ?? missing("job", id);
  }

  create(input: JobCreate, stage: Stage, now: number): Job {
    if (this.get(input.id)) conflict("job id already exists");
    this.db.query(`
      INSERT INTO jobs (
        id, title, description, stage, priority, owner, project,
        revision, created_at, updated_at, archived_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, NULL)
    `).run(
      input.id,
      input.title,
      input.description,
      stage,
      input.priority,
      input.owner,
      input.project,
      now,
      now,
    );
    return this.require(input.id);
  }

  patch(id: string, patch: JobPatch, now: number): Job {
    const current = this.require(id);
    revisionMatches(current.revision, patch.expectedRevision);
    this.db.query(`
      UPDATE jobs SET title = ?, description = ?, priority = ?, owner = ?,
        revision = revision + 1, updated_at = ? WHERE id = ? AND revision = ?
    `).run(
      patch.title ?? current.title,
      patch.description ?? current.description,
      patch.priority ?? current.priority,
      patch.owner ?? current.owner,
      now,
      id,
      patch.expectedRevision,
    );
    return this.require(id);
  }

  transition(id: string, stage: Stage, revision: number, now: number): Job {
    revisionMatches(this.require(id).revision, revision);
    this.db.query(`
      UPDATE jobs SET stage = ?, revision = revision + 1, updated_at = ?
      WHERE id = ? AND revision = ?
    `).run(stage, now, id, revision);
    return this.require(id);
  }

  archive(id: string, revision: number, now: number): Job {
    const current = this.require(id);
    revisionMatches(current.revision, revision);
    if (current.archivedAt !== null) conflict("job already archived");
    this.db.query(`
      UPDATE jobs SET archived_at = ?, updated_at = ?, revision = revision + 1
      WHERE id = ? AND revision = ?
    `).run(now, now, id, revision);
    return this.require(id);
  }

  restore(id: string, revision: number, now: number): Job {
    const current = this.require(id);
    revisionMatches(current.revision, revision);
    if (current.archivedAt === null) conflict("job is not archived");
    this.db.query(`
      UPDATE jobs SET archived_at = NULL, updated_at = ?, revision = revision + 1
      WHERE id = ? AND revision = ?
    `).run(now, id, revision);
    return this.require(id);
  }

  delete(id: string): void {
    this.require(id);
    this.db.query("DELETE FROM jobs WHERE id = ?").run(id);
  }

  count(project?: string): number {
    if (project !== undefined) {
      return this.db.query<{ count: number }, [string]>(
        "SELECT COUNT(*) AS count FROM jobs WHERE project = ? AND archived_at IS NULL",
      ).get(project)!.count;
    }
    return this.db.query<{ count: number }, []>(
      "SELECT COUNT(*) AS count FROM jobs WHERE archived_at IS NULL",
    ).get()!.count;
  }

  list(filter: JobFilter): Page<Job> {
    const conditions: string[] = [];
    const bindings: SQLQueryBindings[] = [];
    if (filter.stage !== undefined) {
      conditions.push("stage = ?");
      bindings.push(filter.stage);
    }
    if (filter.owner !== undefined) {
      conditions.push("owner = ?");
      bindings.push(filter.owner);
    }
    if (filter.project !== undefined) {
      conditions.push("project = ?");
      bindings.push(filter.project);
    }
    if (filter.minPriority !== undefined) {
      conditions.push("priority >= ?");
      bindings.push(filter.minPriority);
    }
    if (filter.archived !== undefined) {
      conditions.push(filter.archived ? "archived_at IS NOT NULL" : "archived_at IS NULL");
    }
    if (filter.query) {
      conditions.push("(title LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\')");
      const escaped = filter.query.replace(/[\\%_]/g, match => `\\${match}`);
      bindings.push(`%${escaped}%`, `%${escaped}%`);
    }
    const where = conditions.length ? `WHERE ${conditions.join(" AND ")}` : "";
    const total = this.db.query<{ count: number }, SQLQueryBindings[]>(
      `SELECT COUNT(*) AS count FROM jobs ${where}`,
    ).get(...bindings)!.count;
    const rows = this.db.query<JobRow, SQLQueryBindings[]>(`
      SELECT * FROM jobs ${where}
      ORDER BY priority DESC, created_at ASC, id ASC LIMIT ? OFFSET ?
    `).all(...bindings, filter.limit, filter.offset);
    return {
      items: rows.map(decode),
      total,
      limit: filter.limit,
      offset: filter.offset,
      nextOffset: filter.offset + rows.length < total ? filter.offset + rows.length : null,
    };
  }

  allInProject(project: string): Job[] {
    return this.list({ project, limit: -1, offset: 0 }).items;
  }

  olderArchived(before: number, limit: number, project?: string): string[] {
    return this.db.query<{ id: string }, SQLQueryBindings[]>(`
      SELECT id FROM jobs WHERE archived_at IS NOT NULL AND archived_at < ?
      ${project === undefined ? "" : "AND project = ?"}
      ORDER BY archived_at ASC, id ASC LIMIT ?
    `).all(before, ...(project === undefined ? [] : [project]), limit).map(row => row.id);
  }
}
