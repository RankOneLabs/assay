import type { Database } from "bun:sqlite";
import { revisionMatches } from "../domain/errors.ts";
import {
  settingsDefaults,
  type ProjectSettings, type SettingsChange, type SettingsHistoryEntry, type SettingsValues,
} from "../domain/settings.ts";

interface SettingsRow {
  project: string;
  wip_limit: number;
  evidence_quota_bytes: number;
  default_review_owner: string | null;
  stale_after_days: number;
  revision: number;
  updated_by: string;
  updated_at: number;
}

interface HistoryRow {
  revision: number;
  actor: string;
  changes: string;
  reason: string | null;
  created_at: number;
}

function decode(row: SettingsRow): ProjectSettings {
  return {
    project: row.project,
    wipLimit: row.wip_limit,
    evidenceQuotaBytes: row.evidence_quota_bytes,
    defaultReviewOwner: row.default_review_owner,
    staleAfterDays: row.stale_after_days,
    revision: row.revision,
    updatedBy: row.updated_by,
    updatedAt: row.updated_at,
  };
}

/** One settings record per project; a project without a record uses the defaults at revision 0. */
export class SettingsRepository {
  constructor(private readonly db: Database) {}

  get(project: string): ProjectSettings {
    const row = this.db.query<SettingsRow, [string]>(
      "SELECT * FROM project_settings WHERE project = ?",
    ).get(project);
    return row ? decode(row) : { project, ...settingsDefaults, revision: 0, updatedBy: null, updatedAt: null };
  }

  save(project: string, values: SettingsValues, expectedRevision: number, actor: string, now: number): ProjectSettings {
    revisionMatches(this.get(project).revision, expectedRevision);
    const columns = [
      values.wipLimit, values.evidenceQuotaBytes, values.defaultReviewOwner, values.staleAfterDays, actor, now,
    ] as const;
    if (expectedRevision === 0) {
      this.db.query(`
        INSERT INTO project_settings (
          wip_limit, evidence_quota_bytes, default_review_owner, stale_after_days,
          updated_by, updated_at, project, revision
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
      `).run(...columns, project);
    } else {
      this.db.query(`
        UPDATE project_settings SET wip_limit = ?, evidence_quota_bytes = ?, default_review_owner = ?,
          stale_after_days = ?, updated_by = ?, updated_at = ?, revision = revision + 1
        WHERE project = ? AND revision = ?
      `).run(...columns, project, expectedRevision);
    }
    return this.get(project);
  }

  appendHistory(
    project: string,
    revision: number,
    actor: string,
    changes: SettingsChange[],
    reason: string | null,
    now: number,
  ): void {
    this.db.query(`
      INSERT INTO project_settings_history (project, revision, actor, changes, reason, created_at)
      VALUES (?, ?, ?, ?, ?, ?)
    `).run(project, revision, actor, JSON.stringify(changes), reason, now);
  }

  history(project: string, after: number, limit: number): SettingsHistoryEntry[] {
    return this.db.query<HistoryRow, [string, number, number]>(`
      SELECT revision, actor, changes, reason, created_at FROM project_settings_history
      WHERE project = ? AND revision > ? ORDER BY revision ASC LIMIT ?
    `).all(project, after, limit).map(row => ({
      revision: row.revision,
      actor: row.actor,
      changes: JSON.parse(row.changes) as SettingsChange[],
      reason: row.reason,
      createdAt: row.created_at,
    }));
  }
}
