import type { Database } from "bun:sqlite";
import type { JobEvent } from "../domain/models.ts";

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

/** Events are durable history; consumers page by sequence, never by wall time. */
export class EventRepository {
  constructor(private readonly db: Database) {}

  append(jobId: string, action: string, actor: string, detail: unknown, now: number): JobEvent {
    const result = this.db.query(`
      INSERT INTO job_events (job_id, action, actor, detail, created_at) VALUES (?, ?, ?, ?, ?)
    `).run(jobId, action, actor, JSON.stringify(detail), now);
    return this.get(Number(result.lastInsertRowid))!;
  }

  get(sequence: number): JobEvent | null {
    const row = this.db.query<EventRow, [number]>(
      "SELECT * FROM job_events WHERE sequence = ?",
    ).get(sequence);
    return row ? decode(row) : null;
  }

  list(jobId: string, after = 0, limit = 100): JobEvent[] {
    return this.db.query<EventRow, [string, number, number]>(`
      SELECT * FROM job_events WHERE job_id = ? AND sequence > ?
      ORDER BY sequence ASC LIMIT ?
    `).all(jobId, after, limit).map(decode);
  }

  all(jobId: string): JobEvent[] {
    return this.db.query<EventRow, [string]>(`
      SELECT * FROM job_events WHERE job_id = ? ORDER BY sequence ASC
    `).all(jobId).map(decode);
  }

  count(jobId: string): number {
    return this.db.query<{ count: number }, [string]>(
      "SELECT COUNT(*) AS count FROM job_events WHERE job_id = ?",
    ).get(jobId)!.count;
  }
}
