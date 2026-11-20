import type { Database, SQLQueryBindings } from "bun:sqlite";
import type { JobEvent } from "../domain/models.ts";
import type { AuditDimension, AuditFilter, AuditGroup } from "../domain/audit.ts";

interface EventRow {
  sequence: number;
  job_id: string;
  action: string;
  actor: string;
  detail: string;
  created_at: number;
}

function decode(row: EventRow): JobEvent {
  return {
    sequence: row.sequence,
    jobId: row.job_id,
    action: row.action,
    actor: row.actor,
    detail: row.detail,
    createdAt: row.created_at,
  };
}

/** Days are UTC calendar dates of the event's millisecond timestamp. */
const groupKeys: Record<AuditDimension, string> = {
  actor: "e.actor",
  action: "e.action",
  day: "strftime('%Y-%m-%d', e.created_at / 1000, 'unixepoch')",
};

/** Read-only queries across a project's event log; rows reach a project only through their job. */
export class AuditRepository {
  constructor(private readonly db: Database) {}

  /** Events after a sequence cursor, oldest first. */
  page(project: string, filter: AuditFilter, after: number, limit: number): JobEvent[] {
    const { where, bindings } = this.where(project, filter);
    return this.db.query<EventRow, SQLQueryBindings[]>(`
      SELECT e.* FROM job_events e JOIN jobs j ON j.id = e.job_id
      ${where} AND e.sequence > ? ORDER BY e.sequence ASC LIMIT ?
    `).all(...bindings, after, limit).map(decode);
  }

  summarize(project: string, filter: AuditFilter, by: AuditDimension): AuditGroup[] {
    const { where, bindings } = this.where(project, filter);
    const key = groupKeys[by];
    const order = by === "day" ? "key ASC" : "count DESC, key ASC";
    return this.db.query<AuditGroup, SQLQueryBindings[]>(`
      SELECT ${key} AS key, COUNT(*) AS count, COUNT(DISTINCT e.job_id) AS jobs,
        MIN(e.created_at) AS first, MAX(e.created_at) AS last
      FROM job_events e JOIN jobs j ON j.id = e.job_id
      ${where} GROUP BY key ORDER BY ${order}
    `).all(...bindings);
  }

  transitions(jobId: string): JobEvent[] {
    return this.db.query<EventRow, [string]>(`
      SELECT * FROM job_events WHERE job_id = ? AND action = 'job.transitioned' ORDER BY sequence ASC
    `).all(jobId).map(decode);
  }

  /** Every transition in a project, grouped by job in one pass instead of a query per job. */
  projectTransitions(project: string): Map<string, JobEvent[]> {
    const grouped = new Map<string, JobEvent[]>();
    const rows = this.db.query<EventRow, [string]>(`
      SELECT e.* FROM job_events e JOIN jobs j ON j.id = e.job_id
      WHERE j.project = ? AND e.action = 'job.transitioned' ORDER BY e.sequence ASC
    `).all(project);
    for (const row of rows) {
      const event = decode(row);
      grouped.set(event.jobId, [...(grouped.get(event.jobId) ?? []), event]);
    }
    return grouped;
  }

  private where(project: string, filter: AuditFilter): { where: string; bindings: SQLQueryBindings[] } {
    const conditions = ["j.project = ?"];
    const bindings: SQLQueryBindings[] = [project];
    if (filter.actor !== undefined) {
      conditions.push("e.actor = ?");
      bindings.push(filter.actor);
    }
    if (filter.action !== undefined) {
      conditions.push("e.action LIKE ? ESCAPE '\\'");
      bindings.push(`${filter.action.replace(/[\\%_]/g, match => `\\${match}`)}%`);
    }
    if (filter.jobId !== undefined) {
      conditions.push("e.job_id = ?");
      bindings.push(filter.jobId);
    }
    if (filter.from !== undefined) {
      conditions.push("e.created_at >= ?");
      bindings.push(filter.from);
    }
    if (filter.to !== undefined) {
      conditions.push("e.created_at < ?");
      bindings.push(filter.to);
    }
    return { where: `WHERE ${conditions.join(" AND ")}`, bindings };
  }
}
