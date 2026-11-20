import type { Database } from "bun:sqlite";
import { secretHint, type WebhookEndpoint } from "../domain/webhooks.ts";
import { conflict, missing, revisionMatches } from "../domain/errors.ts";

interface WebhookRow {
  id: string;
  project: string;
  url: string;
  secret: string;
  active: number;
  revision: number;
  created_at: number;
  updated_at: number;
}

/** The secret leaves the repository only through secret(). */
function decode(row: WebhookRow): WebhookEndpoint {
  return {
    id: row.id,
    project: row.project,
    url: row.url,
    active: row.active === 1,
    revision: row.revision,
    secretHint: secretHint(row.secret),
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

export type WebhookFields = Pick<WebhookEndpoint, "url" | "active">;

export class WebhookRepository {
  constructor(private readonly db: Database) {}

  get(id: string): WebhookEndpoint | null {
    const row = this.db.query<WebhookRow, [string]>("SELECT * FROM webhook_endpoints WHERE id = ?").get(id);
    return row ? decode(row) : null;
  }

  require(id: string): WebhookEndpoint {
    return this.get(id) ?? missing("webhook", id);
  }

  secret(id: string): string {
    return this.db.query<{ secret: string }, [string]>(
      "SELECT secret FROM webhook_endpoints WHERE id = ?",
    ).get(id)?.secret ?? missing("webhook", id);
  }

  list(project: string): WebhookEndpoint[] {
    return this.db.query<WebhookRow, [string]>(
      "SELECT * FROM webhook_endpoints WHERE project = ? ORDER BY id",
    ).all(project).map(decode);
  }

  create(id: string, project: string, fields: WebhookFields, secret: string, now: number): WebhookEndpoint {
    if (this.get(id)) conflict("webhook id already exists");
    this.db.query(`
      INSERT INTO webhook_endpoints (id, project, url, secret, active, revision, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, 1, ?, ?)
    `).run(id, project, fields.url, secret, fields.active ? 1 : 0, now, now);
    return this.require(id);
  }

  update(id: string, fields: WebhookFields, expectedRevision: number, now: number): WebhookEndpoint {
    revisionMatches(this.require(id).revision, expectedRevision);
    this.db.query(`
      UPDATE webhook_endpoints SET url = ?, active = ?, revision = revision + 1, updated_at = ?
      WHERE id = ? AND revision = ?
    `).run(fields.url, fields.active ? 1 : 0, now, id, expectedRevision);
    return this.require(id);
  }

  rotate(id: string, secret: string, expectedRevision: number, now: number): WebhookEndpoint {
    revisionMatches(this.require(id).revision, expectedRevision);
    this.db.query(`
      UPDATE webhook_endpoints SET secret = ?, revision = revision + 1, updated_at = ? WHERE id = ? AND revision = ?
    `).run(secret, now, id, expectedRevision);
    return this.require(id);
  }

  delete(id: string, expectedRevision: number): void {
    revisionMatches(this.require(id).revision, expectedRevision);
    this.db.query("DELETE FROM webhook_endpoints WHERE id = ?").run(id);
  }
}
