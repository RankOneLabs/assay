import type { Database } from "bun:sqlite";
import type { Attempt } from "../domain/models.ts";
import { conflict, missing } from "../domain/errors.ts";

interface AttemptRow {
  id: string;
  job_id: string;
  session_id: string;
  worker: string;
  started_at: number;
  finished_at: number | null;
  exit_code: number | null;
  output: string;
}

function decode(row: AttemptRow): Attempt {
  return {
    id: row.id,
    jobId: row.job_id,
    sessionId: row.session_id,
    worker: row.worker,
    startedAt: row.started_at,
    finishedAt: row.finished_at,
    exitCode: row.exit_code,
    output: row.output,
  };
}

/** Attempts record historical outcomes; running status belongs to SessionService. */
export class AttemptRepository {
  constructor(private readonly db: Database) {}

  get(id: string): Attempt | null {
    const row = this.db.query<AttemptRow, [string]>("SELECT * FROM attempts WHERE id = ?").get(id);
    return row ? decode(row) : null;
  }

  require(id: string): Attempt {
    return this.get(id) ?? missing("attempt", id);
  }

  bySession(sessionId: string): Attempt | null {
    const row = this.db.query<AttemptRow, [string]>(
      "SELECT * FROM attempts WHERE session_id = ?",
    ).get(sessionId);
    return row ? decode(row) : null;
  }

  list(jobId: string): Attempt[] {
    return this.db.query<AttemptRow, [string]>(`
      SELECT * FROM attempts WHERE job_id = ? ORDER BY started_at, id
    `).all(jobId).map(decode);
  }

  create(id: string, jobId: string, sessionId: string, worker: string, now: number): Attempt {
    if (this.get(id)) conflict("attempt id already exists");
    if (this.bySession(sessionId)) conflict("session id already used");
    this.db.query(`
      INSERT INTO attempts (id, job_id, session_id, worker, started_at, output)
      VALUES (?, ?, ?, ?, ?, '')
    `).run(id, jobId, sessionId, worker, now);
    return this.require(id);
  }

  finish(sessionId: string, exitCode: number, output: string, now: number): Attempt {
    const current = this.bySession(sessionId) ?? missing("session", sessionId);
    if (current.finishedAt !== null) conflict("attempt already finished");
    this.db.query(`
      UPDATE attempts SET finished_at = ?, exit_code = ?, output = ? WHERE session_id = ?
    `).run(now, exitCode, output, sessionId);
    return this.require(current.id);
  }
}
