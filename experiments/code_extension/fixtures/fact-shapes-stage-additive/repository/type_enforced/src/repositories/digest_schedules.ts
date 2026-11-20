import type { Database } from "bun:sqlite";
import type { Principal } from "../domain/models.ts";
import type { Cadence, Recurrence } from "../domain/schedules.ts";
import { conflict, missing, revisionMatches } from "../domain/errors.ts";

export interface ScheduleValues extends Recurrence {
  enabled: boolean;
}

export interface DigestSchedule extends ScheduleValues {
  id: string;
  principal: string;
  project: string;
  revision: number;
  nextRunAt: number;
  lastRunAt: number | null;
  createdAt: number;
  updatedAt: number;
}

interface ScheduleRow {
  id: string;
  principal: string;
  project: string;
  cadence: Cadence;
  weekday: number | null;
  hour: number;
  utc_offset_minutes: number;
  enabled: number;
  revision: number;
  next_run_at: number;
  last_run_at: number | null;
  created_at: number;
  updated_at: number;
}

function decode(row: ScheduleRow): DigestSchedule {
  return {
    id: row.id,
    principal: row.principal,
    project: row.project,
    cadence: row.cadence,
    weekday: row.weekday,
    hour: row.hour,
    utcOffsetMinutes: row.utc_offset_minutes,
    enabled: row.enabled === 1,
    revision: row.revision,
    nextRunAt: row.next_run_at,
    lastRunAt: row.last_run_at,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

export class DigestScheduleRepository {
  constructor(private readonly db: Database) {}

  get(id: string): DigestSchedule | null {
    const row = this.db.query<ScheduleRow, [string]>("SELECT * FROM digest_schedules WHERE id = ?").get(id);
    return row ? decode(row) : null;
  }

  require(id: string): DigestSchedule {
    return this.get(id) ?? missing("digest schedule", id);
  }

  create(id: string, owner: Principal, values: ScheduleValues, nextRunAt: number, now: number): DigestSchedule {
    if (this.get(id)) conflict("digest schedule id already exists");
    this.db.query(`
      INSERT INTO digest_schedules (
        id, principal, project, cadence, weekday, hour, utc_offset_minutes, enabled,
        revision, next_run_at, last_run_at, created_at, updated_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, NULL, ?, ?)
    `).run(
      id, owner.id, owner.project, values.cadence, values.weekday, values.hour,
      values.utcOffsetMinutes, values.enabled ? 1 : 0, nextRunAt, now, now,
    );
    return this.require(id);
  }

  update(id: string, values: ScheduleValues, expectedRevision: number, nextRunAt: number, now: number): DigestSchedule {
    revisionMatches(this.require(id).revision, expectedRevision);
    this.db.query(`
      UPDATE digest_schedules SET cadence = ?, weekday = ?, hour = ?, utc_offset_minutes = ?,
        enabled = ?, next_run_at = ?, revision = revision + 1, updated_at = ?
      WHERE id = ? AND revision = ?
    `).run(
      values.cadence, values.weekday, values.hour, values.utcOffsetMinutes, values.enabled ? 1 : 0,
      nextRunAt, now, id, expectedRevision,
    );
    return this.require(id);
  }

  /** Record a completed run; the revision moves so stale edits cannot undo it. */
  advance(id: string, ranAt: number, nextRunAt: number, now: number): DigestSchedule {
    this.db.query(`
      UPDATE digest_schedules SET last_run_at = ?, next_run_at = ?, revision = revision + 1, updated_at = ?
      WHERE id = ?
    `).run(ranAt, nextRunAt, now, id);
    return this.require(id);
  }

  owned(owner: Principal): DigestSchedule[] {
    return this.db.query<ScheduleRow, [string, string]>(`
      SELECT * FROM digest_schedules WHERE project = ? AND principal = ? ORDER BY id
    `).all(owner.project, owner.id).map(decode);
  }

  due(project: string, at: number, limit: number): DigestSchedule[] {
    return this.db.query<ScheduleRow, [string, number, number]>(`
      SELECT * FROM digest_schedules WHERE project = ? AND enabled = 1 AND next_run_at <= ?
      ORDER BY next_run_at ASC, id ASC LIMIT ?
    `).all(project, at, limit).map(decode);
  }
}
