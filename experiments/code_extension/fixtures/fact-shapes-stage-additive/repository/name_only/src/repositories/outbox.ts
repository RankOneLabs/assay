import type { Database } from "bun:sqlite";
import type { Stage } from "../../stage/types.ts";
import type { Job, JobEvent } from "../domain/models.ts";

interface EventJobRow {
  sequence: number;
  job_id: string;
  action: string;
  actor: string;
  detail: string;
  created_at: number;
  project: string;
  title: string;
  stage: Stage;
}

/** A job event together with its job as the job stands when the event is collected. */
export interface CollectableEvent {
  event: JobEvent;
  job: Pick<Job, "project" | "title" | "stage">;
}

/** Reads job_events by sequence behind a per-project cursor that only moves forward. */
export class OutboxRepository {
  constructor(private readonly db: Database) {}

  cursor(project: string): number {
    return this.db.query<{ sequence: number }, [string]>(
      "SELECT sequence FROM outbox_cursors WHERE project = ?",
    ).get(project)?.sequence ?? 0;
  }

  advance(project: string, sequence: number, actor: string, now: number): void {
    this.db.query(`
      INSERT INTO outbox_cursors (project, sequence, collected_by, updated_at) VALUES (?, ?, ?, ?)
      ON CONFLICT (project) DO UPDATE SET sequence = MAX(sequence, excluded.sequence),
        collected_by = excluded.collected_by, updated_at = excluded.updated_at
    `).run(project, sequence, actor, now);
  }

  eventsAfter(project: string, after: number, limit: number): CollectableEvent[] {
    return this.db.query<EventJobRow, [string, number, number]>(`
      SELECT e.*, j.project, j.title, j.stage FROM job_events e JOIN jobs j ON j.id = e.job_id
      WHERE j.project = ? AND e.sequence > ? ORDER BY e.sequence ASC LIMIT ?
    `).all(project, after, limit).map(row => ({
      event: {
        sequence: row.sequence,
        jobId: row.job_id,
        action: row.action,
        actor: row.actor,
        detail: row.detail,
        createdAt: row.created_at,
      },
      job: { project: row.project, title: row.title, stage: row.stage },
    }));
  }
}
