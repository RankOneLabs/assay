import type { Database } from "bun:sqlite";
import type { JobEvent } from "../domain/models.ts";
import { missing } from "../domain/errors.ts";
import type { AttemptOutcome, DeliveryStatus, WebhookDelivery } from "../domain/webhooks.ts";

interface DeliveryRow {
  id: number;
  webhook_id: string;
  event_sequence: number;
  action: string;
  payload: string;
  status: DeliveryStatus;
  attempts: number;
  next_attempt_at: number;
  lease_owner: string | null;
  lease_expires_at: number | null;
  last_status: number | null;
  updated_at: number;
}

/** The lease token is a bearer credential for one report, so it is never decoded. */
function decode(row: DeliveryRow): WebhookDelivery {
  return {
    id: row.id,
    webhookId: row.webhook_id,
    eventSequence: row.event_sequence,
    action: row.action,
    payload: row.payload,
    status: row.status,
    attempts: row.attempts,
    nextAttemptAt: row.next_attempt_at,
    leaseOwner: row.lease_owner,
    leaseExpiresAt: row.lease_expires_at,
    lastStatus: row.last_status,
    updatedAt: row.updated_at,
  };
}

const clearLease = "lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL";

export class DeliveryRepository {
  constructor(private readonly db: Database) {}

  require(project: string, id: number): WebhookDelivery {
    const row = this.db.query<DeliveryRow, [number, string]>(
      "SELECT * FROM webhook_deliveries WHERE id = ? AND project = ?",
    ).get(id, project);
    return row ? decode(row) : missing("delivery", String(id));
  }

  /** One delivery per endpoint and event, however often the event is collected. */
  enqueue(project: string, webhookId: string, event: JobEvent, payload: string, now: number): boolean {
    return this.db.query(`
      INSERT OR IGNORE INTO webhook_deliveries (
        project, webhook_id, event_sequence, job_id, action, payload, status, attempts,
        next_attempt_at, created_at, updated_at
      ) VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)
    `).run(project, webhookId, event.sequence, event.jobId, event.action, payload, now, now, now).changes > 0;
  }

  /** Pending deliveries to active endpoints whose retry time has come and whose lease is free. */
  due(project: string, now: number, limit: number): WebhookDelivery[] {
    return this.db.query<DeliveryRow, [string, number, number, number]>(`
      SELECT d.* FROM webhook_deliveries d JOIN webhook_endpoints w ON w.id = d.webhook_id
      WHERE d.project = ? AND d.status = 'pending' AND w.active = 1 AND d.next_attempt_at <= ?
        AND (d.lease_expires_at IS NULL OR d.lease_expires_at <= ?)
      ORDER BY d.next_attempt_at ASC, d.id ASC LIMIT ?
    `).all(project, now, now, limit).map(decode);
  }

  lease(id: number, worker: string, token: string, expiresAt: number, now: number): void {
    this.db.query(`
      UPDATE webhook_deliveries SET lease_owner = ?, lease_token = ?, lease_expires_at = ?, updated_at = ?
      WHERE id = ?
    `).run(worker, token, expiresAt, now, id);
  }

  leaseHeld(id: number, token: string, now: number): boolean {
    return this.db.query<{ found: number }, [number, string, number]>(`
      SELECT 1 AS found FROM webhook_deliveries
      WHERE id = ? AND status = 'pending' AND lease_token = ? AND lease_expires_at > ?
    `).get(id, token, now) !== null;
  }

  record(id: number, outcome: AttemptOutcome, httpStatus: number, now: number): void {
    this.db.query(`
      UPDATE webhook_deliveries SET status = ?, attempts = ?, next_attempt_at = ?, last_status = ?,
        ${clearLease}, updated_at = ? WHERE id = ?
    `).run(outcome.status, outcome.attempts, outcome.nextAttemptAt, httpStatus, now, id);
  }

  /** A fresh attempt budget, due now; the last response status stays for the record. */
  redeliver(id: number, now: number): void {
    this.db.query(`
      UPDATE webhook_deliveries SET status = 'pending', attempts = 0, next_attempt_at = ?, ${clearLease},
        updated_at = ? WHERE id = ?
    `).run(now, now, id);
  }

  /** Most recently failed first. */
  deadLetters(project: string, limit: number): WebhookDelivery[] {
    return this.db.query<DeliveryRow, [string, number]>(`
      SELECT * FROM webhook_deliveries WHERE project = ? AND status = 'dead'
      ORDER BY updated_at DESC, id DESC LIMIT ?
    `).all(project, limit).map(decode);
  }
}
