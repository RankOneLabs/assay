import type { Database } from "bun:sqlite";
import type { Stage } from "../../stage/types.ts";
import type { Subscription } from "../domain/notifications.ts";
import { conflict } from "../domain/errors.ts";

interface SubscriptionRow {
  id: string;
  project: string;
  principal: string;
  pattern: string;
  job_id: string | null;
  stage: Stage | null;
  created_at: number;
}

function decode(row: SubscriptionRow): Subscription {
  return {
    id: row.id,
    project: row.project,
    principal: row.principal,
    pattern: row.pattern,
    jobId: row.job_id,
    stage: row.stage,
    createdAt: row.created_at,
  };
}

export class SubscriptionRepository {
  constructor(private readonly db: Database) {}

  get(id: string): Subscription | null {
    const row = this.db.query<SubscriptionRow, [string]>("SELECT * FROM subscriptions WHERE id = ?").get(id);
    return row ? decode(row) : null;
  }

  create(input: Omit<Subscription, "createdAt">, now: number): Subscription {
    if (this.get(input.id)) conflict("subscription id already exists");
    this.db.query(`
      INSERT INTO subscriptions (id, project, principal, pattern, job_id, stage, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `).run(input.id, input.project, input.principal, input.pattern, input.jobId, input.stage, now);
    return this.get(input.id)!;
  }

  forPrincipal(project: string, principal: string): Subscription[] {
    return this.db.query<SubscriptionRow, [string, string]>(`
      SELECT * FROM subscriptions WHERE project = ? AND principal = ? ORDER BY id
    `).all(project, principal).map(decode);
  }

  /** Ordered by principal, then id, so the first match per principal is deterministic. */
  forProject(project: string): Subscription[] {
    return this.db.query<SubscriptionRow, [string]>(`
      SELECT * FROM subscriptions WHERE project = ? ORDER BY principal, id
    `).all(project).map(decode);
  }

  delete(id: string): void {
    this.db.query("DELETE FROM subscriptions WHERE id = ?").run(id);
  }
}
