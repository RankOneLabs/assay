import type { Database } from "bun:sqlite";
import type { Page, Principal } from "../domain/models.ts";
import { missing } from "../domain/errors.ts";

export interface StoredDigest {
  id: number;
  scheduleId: string;
  principal: string;
  project: string;
  periodStart: number;
  periodEnd: number;
  content: string;
  checksum: string;
  generatedBy: string;
  createdAt: number;
}

const columns = `
  id, schedule_id AS scheduleId, principal, project, period_start AS periodStart,
  period_end AS periodEnd, content, checksum, generated_by AS generatedBy, created_at AS createdAt
`;

export class DigestRepository {
  constructor(private readonly db: Database) {}

  get(id: number): StoredDigest | null {
    return this.db.query<StoredDigest, [number]>(`SELECT ${columns} FROM digests WHERE id = ?`).get(id);
  }

  require(id: number): StoredDigest {
    return this.get(id) ?? missing("digest", String(id));
  }

  create(input: Omit<StoredDigest, "id" | "createdAt">, now: number): StoredDigest {
    const result = this.db.query(`
      INSERT INTO digests (
        schedule_id, principal, project, period_start, period_end, content, checksum, generated_by, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).run(
      input.scheduleId, input.principal, input.project, input.periodStart, input.periodEnd,
      input.content, input.checksum, input.generatedBy, now,
    );
    return this.require(Number(result.lastInsertRowid));
  }

  list(owner: Principal, limit: number, offset: number): Page<StoredDigest> {
    const total = this.db.query<{ count: number }, [string, string]>(
      "SELECT COUNT(*) AS count FROM digests WHERE project = ? AND principal = ?",
    ).get(owner.project, owner.id)!.count;
    const items = this.db.query<StoredDigest, [string, string, number, number]>(`
      SELECT ${columns} FROM digests WHERE project = ? AND principal = ?
      ORDER BY period_end DESC, id DESC LIMIT ? OFFSET ?
    `).all(owner.project, owner.id, limit, offset);
    return {
      items,
      total,
      limit,
      offset,
      nextOffset: offset + items.length < total ? offset + items.length : null,
    };
  }

  /** Counts over [from, to); grouped counts are keyed by the stored stage or kind. */
  activity(project: string, from: number, to: number) {
    const count = (sql: string) =>
      this.db.query<{ count: number }, [string, number, number]>(sql).get(project, from, to)!.count;
    const grouped = (sql: string) => new Map(
      this.db.query<{ key: string; count: number }, [string, number, number]>(sql)
        .all(project, from, to).map(row => [row.key, row.count]),
    );
    return {
      created: count(`
        SELECT COUNT(*) AS count FROM jobs WHERE project = ? AND created_at >= ? AND created_at < ?
      `),
      changed: count(`
        SELECT COUNT(DISTINCT e.job_id) AS count FROM job_events e JOIN jobs j ON j.id = e.job_id
        WHERE j.project = ? AND e.created_at >= ? AND e.created_at < ? AND e.action != 'job.created'
      `),
      transitions: grouped(`
        SELECT json_extract(e.detail, '$.to') AS key, COUNT(*) AS count
        FROM job_events e JOIN jobs j ON j.id = e.job_id
        WHERE j.project = ? AND e.created_at >= ? AND e.created_at < ? AND e.action = 'job.transitioned'
        GROUP BY key
      `),
      evidence: grouped(`
        SELECT e.kind AS key, COUNT(*) AS count FROM evidence e JOIN jobs j ON j.id = e.job_id
        WHERE j.project = ? AND e.created_at >= ? AND e.created_at < ?
        GROUP BY e.kind
      `),
    };
  }
}
