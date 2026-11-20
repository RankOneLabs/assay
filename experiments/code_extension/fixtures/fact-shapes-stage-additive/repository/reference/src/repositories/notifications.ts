import type { Database } from "bun:sqlite";
import type { JobEvent, Principal } from "../domain/models.ts";
import type { Notification } from "../domain/notifications.ts";

interface NotificationRow {
  id: number;
  subscription_id: string | null;
  job_id: string;
  action: string;
  payload: string;
  created_at: number;
  read_at: number | null;
}

function decode(row: NotificationRow): Notification {
  return {
    id: row.id,
    subscriptionId: row.subscription_id,
    jobId: row.job_id,
    action: row.action,
    payload: JSON.parse(row.payload) as unknown,
    createdAt: row.created_at,
    readAt: row.read_at,
  };
}

export class NotificationRepository {
  constructor(private readonly db: Database) {}

  /** One notification per recipient and event, however many of their subscriptions match. */
  insert(recipient: Principal, subscriptionId: string, event: JobEvent, payload: string, now: number): boolean {
    return this.db.query(`
      INSERT OR IGNORE INTO notifications (
        project, principal, subscription_id, event_sequence, job_id, action, payload, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `).run(
      recipient.project, recipient.id, subscriptionId, event.sequence, event.jobId, event.action, payload, now,
    ).changes > 0;
  }

  inbox(recipient: Principal, unread: boolean, limit: number): Notification[] {
    return this.db.query<NotificationRow, [string, string, number]>(`
      SELECT * FROM notifications WHERE project = ? AND principal = ? ${unread ? "AND read_at IS NULL" : ""}
      ORDER BY id DESC LIMIT ?
    `).all(recipient.project, recipient.id, limit).map(decode);
  }

  markRead(recipient: Principal, ids: readonly number[], now: number): number {
    return this.db.query(`
      UPDATE notifications SET read_at = ?
      WHERE project = ? AND principal = ? AND read_at IS NULL AND id IN (SELECT value FROM json_each(?))
    `).run(now, recipient.project, recipient.id, JSON.stringify(ids)).changes;
  }

  countsByAction(recipient: Principal): { action: string; unread: number; total: number }[] {
    return this.db.query<{ action: string; unread: number; total: number }, [string, string]>(`
      SELECT action, SUM(read_at IS NULL) AS unread, COUNT(*) AS total
      FROM notifications WHERE project = ? AND principal = ? GROUP BY action ORDER BY action
    `).all(recipient.project, recipient.id);
  }
}
