import type { Database, SQLQueryBindings } from "bun:sqlite";
import type { Stage } from "../../stage/types.ts";
import { conflict, missing, revisionMatches } from "../domain/errors.ts";

export interface EscalationRule {
  id: string;
  project: string;
  stage: Stage;
  maxAgeMinutes: number;
  minPriority: number;
  target: string;
  enabled: boolean;
  revision: number;
  createdBy: string;
  createdAt: number;
  updatedAt: number;
}

export interface RuleValues {
  stage: Stage;
  maxAgeMinutes: number;
  minPriority: number;
  target: string;
  enabled: boolean;
}

interface RuleRow {
  id: string;
  project: string;
  stage: Stage;
  max_age_minutes: number;
  min_priority: number;
  target: string;
  enabled: number;
  revision: number;
  created_by: string;
  created_at: number;
  updated_at: number;
}

function decode(row: RuleRow): EscalationRule {
  return {
    id: row.id,
    project: row.project,
    stage: row.stage,
    maxAgeMinutes: row.max_age_minutes,
    minPriority: row.min_priority,
    target: row.target,
    enabled: row.enabled === 1,
    revision: row.revision,
    createdBy: row.created_by,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

export class EscalationRuleRepository {
  constructor(private readonly db: Database) {}

  get(id: string): EscalationRule | null {
    const row = this.db.query<RuleRow, [string]>("SELECT * FROM escalation_rules WHERE id = ?").get(id);
    return row ? decode(row) : null;
  }

  require(id: string): EscalationRule {
    return this.get(id) ?? missing("escalation rule", id);
  }

  create(id: string, project: string, values: RuleValues, actor: string, now: number): EscalationRule {
    if (this.get(id)) conflict("escalation rule id already exists");
    this.db.query(`
      INSERT INTO escalation_rules (
        id, project, stage, max_age_minutes, min_priority, target, enabled,
        revision, created_by, created_at, updated_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
    `).run(
      id, project, values.stage, values.maxAgeMinutes, values.minPriority, values.target,
      values.enabled ? 1 : 0, actor, now, now,
    );
    return this.require(id);
  }

  update(id: string, values: RuleValues, expectedRevision: number, now: number): EscalationRule {
    revisionMatches(this.require(id).revision, expectedRevision);
    this.db.query(`
      UPDATE escalation_rules SET stage = ?, max_age_minutes = ?, min_priority = ?, target = ?,
        enabled = ?, revision = revision + 1, updated_at = ?
      WHERE id = ? AND revision = ?
    `).run(
      values.stage, values.maxAgeMinutes, values.minPriority, values.target,
      values.enabled ? 1 : 0, now, id, expectedRevision,
    );
    return this.require(id);
  }

  list(project: string, filter: { stage?: Stage; enabled?: boolean }): EscalationRule[] {
    const conditions = ["project = ?"];
    const bindings: SQLQueryBindings[] = [project];
    if (filter.stage !== undefined) {
      conditions.push("stage = ?");
      bindings.push(filter.stage);
    }
    if (filter.enabled !== undefined) {
      conditions.push("enabled = ?");
      bindings.push(filter.enabled ? 1 : 0);
    }
    return this.db.query<RuleRow, SQLQueryBindings[]>(`
      SELECT * FROM escalation_rules WHERE ${conditions.join(" AND ")} ORDER BY stage, id
    `).all(...bindings).map(decode);
  }

  count(project: string): number {
    return this.db.query<{ count: number }, [string]>(
      "SELECT COUNT(*) AS count FROM escalation_rules WHERE project = ?",
    ).get(project)!.count;
  }
}
