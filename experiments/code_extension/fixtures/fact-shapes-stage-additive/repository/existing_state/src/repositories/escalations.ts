import type { Database, SQLQueryBindings } from "bun:sqlite";
import type { Stage } from "../../stage/types.ts";
import type { Page } from "../domain/models.ts";
import { missing } from "../domain/errors.ts";
import type { EscalationRule } from "./escalation_rules.ts";

export interface Escalation {
  id: number;
  ruleId: string;
  jobId: string;
  project: string;
  stage: Stage;
  target: string;
  ageMinutes: number;
  openedAt: number;
  acknowledgedBy: string | null;
  acknowledgedAt: number | null;
  resolvedBy: string | null;
  resolvedAt: number | null;
  resolution: string | null;
}

export interface EscalationFilter {
  stage?: Stage;
  ruleId?: string;
  target?: string;
  limit: number;
  offset: number;
}

const columns = `
  id, rule_id AS ruleId, job_id AS jobId, project, stage, target, age_minutes AS ageMinutes,
  opened_at AS openedAt, acknowledged_by AS acknowledgedBy, acknowledged_at AS acknowledgedAt,
  resolved_by AS resolvedBy, resolved_at AS resolvedAt, resolution
`;

export class EscalationRepository {
  constructor(private readonly db: Database) {}

  get(id: number): Escalation | null {
    return this.db.query<Escalation, [number]>(`SELECT ${columns} FROM escalations WHERE id = ?`).get(id);
  }

  require(id: number): Escalation {
    return this.get(id) ?? missing("escalation", String(id));
  }

  /** Live jobs a rule covers that were last updated before the cutoff and are not already escalated. */
  stale(rule: EscalationRule, before: number, limit: number): { id: string; updatedAt: number }[] {
    return this.db.query<{ id: string; updatedAt: number }, SQLQueryBindings[]>(`
      SELECT j.id, j.updated_at AS updatedAt FROM jobs j
      WHERE j.project = ? AND j.stage = ? AND j.priority >= ? AND j.updated_at < ?
        AND j.archived_at IS NULL
        AND NOT EXISTS (
          SELECT 1 FROM escalations e
          WHERE e.job_id = j.id AND e.rule_id = ? AND e.resolved_at IS NULL
        )
      ORDER BY j.updated_at ASC, j.id ASC LIMIT ?
    `).all(rule.project, rule.stage, rule.minPriority, before, rule.id, limit);
  }

  open(rule: EscalationRule, jobId: string, ageMinutes: number, at: number): Escalation {
    const result = this.db.query(`
      INSERT INTO escalations (rule_id, job_id, project, stage, target, age_minutes, opened_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `).run(rule.id, jobId, rule.project, rule.stage, rule.target, ageMinutes, at);
    return this.require(Number(result.lastInsertRowid));
  }

  /** Open escalations whose job has since left the escalated stage or been archived. */
  departed(project: string): Escalation[] {
    return this.db.query<Escalation, [string]>(`
      SELECT ${columns} FROM escalations WHERE project = ? AND resolved_at IS NULL
        AND EXISTS (
          SELECT 1 FROM jobs j WHERE j.id = escalations.job_id
            AND (j.stage != escalations.stage OR j.archived_at IS NOT NULL)
        )
      ORDER BY id ASC
    `).all(project);
  }

  acknowledge(id: number, actor: string, now: number): Escalation {
    this.db.query(`
      UPDATE escalations SET acknowledged_by = ?, acknowledged_at = ?
      WHERE id = ? AND acknowledged_at IS NULL AND resolved_at IS NULL
    `).run(actor, now, id);
    return this.require(id);
  }

  resolve(id: number, actor: string, note: string, now: number): Escalation {
    this.db.query(`
      UPDATE escalations SET resolved_by = ?, resolved_at = ?, resolution = ?
      WHERE id = ? AND resolved_at IS NULL
    `).run(actor, now, note, id);
    return this.require(id);
  }

  listOpen(project: string, filter: EscalationFilter): Page<Escalation> {
    const conditions = ["project = ?", "resolved_at IS NULL"];
    const bindings: SQLQueryBindings[] = [project];
    for (const [column, value] of [
      ["stage", filter.stage],
      ["rule_id", filter.ruleId],
      ["target", filter.target],
    ] as const) {
      if (value === undefined) continue;
      conditions.push(`${column} = ?`);
      bindings.push(value);
    }
    const where = conditions.join(" AND ");
    const total = this.db.query<{ count: number }, SQLQueryBindings[]>(
      `SELECT COUNT(*) AS count FROM escalations WHERE ${where}`,
    ).get(...bindings)!.count;
    const items = this.db.query<Escalation, SQLQueryBindings[]>(`
      SELECT ${columns} FROM escalations WHERE ${where} ORDER BY opened_at ASC, id ASC LIMIT ? OFFSET ?
    `).all(...bindings, filter.limit, filter.offset);
    return {
      items,
      total,
      limit: filter.limit,
      offset: filter.offset,
      nextOffset: filter.offset + items.length < total ? filter.offset + items.length : null,
    };
  }

  /** Open and acknowledged counts with the oldest opening, keyed by the stored stage. */
  openByStage(project: string) {
    const rows = this.db.query<{ stage: string; open: number; acknowledged: number; oldestOpenedAt: number }, [string]>(`
      SELECT stage, COUNT(*) AS open, COUNT(acknowledged_at) AS acknowledged,
        MIN(opened_at) AS oldestOpenedAt
      FROM escalations WHERE project = ? AND resolved_at IS NULL GROUP BY stage
    `).all(project);
    return new Map(rows.map(({ stage, ...counts }) => [stage, counts]));
  }
}
