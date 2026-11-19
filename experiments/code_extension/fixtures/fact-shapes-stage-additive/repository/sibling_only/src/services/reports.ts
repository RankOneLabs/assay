import type { Database } from "bun:sqlite";
import type { Principal, Summary, Workload } from "../domain/models.ts";
import { values as stages } from "../../stage/types.ts";
import { values as kinds } from "../../evidence_kind/types.ts";
import { values as permissions } from "../../route_permission/types.ts";
import { stageLabel, evidenceKindLabel, routePermissionLabel } from "../presentation/labels.ts";
import { AccessService } from "./access.ts";
import { byteLength } from "../domain/checksum.ts";

export class ReportService {
  constructor(private readonly db: Database, private readonly access: AccessService) {}

  summary(actor: Principal): Summary {
    this.access.require(actor, "case_read");
    const total = this.db.query<{ count: number }, [string]>(
      "SELECT COUNT(*) AS count FROM jobs WHERE project = ?",
    ).get(actor.project)!.count;
    const archived = this.db.query<{ count: number }, [string]>(
      "SELECT COUNT(*) AS count FROM jobs WHERE project = ? AND archived_at IS NOT NULL",
    ).get(actor.project)!.count;
    return {
      total,
      archived,
      stages: stages.map(stage => ({
        stage,
        label: stageLabel(stage),
        count: this.db.query<{ count: number }, [string, string]>(`
          SELECT COUNT(*) AS count FROM jobs
          WHERE project = ? AND stage = ? AND archived_at IS NULL
        `).get(actor.project, stage)!.count,
      })),
      evidence: kinds.map(kind => {
        const rows = this.db.query<{ content: string }, [string, string]>(`
          SELECT e.content FROM evidence e JOIN jobs j ON j.id = e.job_id
          WHERE j.project = ? AND e.kind = ?
        `).all(actor.project, kind);
        return {
          kind,
          label: evidenceKindLabel(kind),
          count: rows.length,
          bytes: rows.reduce((sum, row) => sum + byteLength(row.content), 0),
        };
      }),
      permissions: permissions.map(permission => ({
        permission,
        label: routePermissionLabel(permission),
        grants: this.db.query<{ count: number }, [string, string]>(
          "SELECT COUNT(*) AS count FROM grants WHERE project = ? AND permission = ?",
        ).get(actor.project, permission)!.count,
      })),
      workloads: this.workloads(actor),
    };
  }

  workloads(actor: Principal): Workload[] {
    this.access.require(actor, "case_read");
    return this.db.query<Workload, [string]>(`
      SELECT owner, COUNT(*) AS jobs, SUM(priority) AS priority FROM jobs
      WHERE project = ? AND archived_at IS NULL
      GROUP BY owner ORDER BY jobs DESC, owner ASC
    `).all(actor.project);
  }

  activity(actor: Principal, since: number, limit: number) {
    this.access.require(actor, "case_read");
    return this.db.query<{
      action: string;
      count: number;
      first: number;
      last: number;
    }, [string, number, number]>(`
      SELECT e.action, COUNT(*) AS count, MIN(e.created_at) AS first, MAX(e.created_at) AS last
      FROM job_events e JOIN jobs j ON j.id = e.job_id
      WHERE j.project = ? AND e.created_at >= ?
      GROUP BY e.action ORDER BY count DESC, e.action ASC LIMIT ?
    `).all(actor.project, since, limit);
  }

  outcomes(actor: Principal) {
    this.access.require(actor, "case_read");
    return this.db.query<{
      worker: string;
      attempts: number;
      succeeded: number;
      failed: number;
      duration: number;
    }, [string]>(`
      SELECT a.worker, COUNT(*) AS attempts,
        SUM(CASE WHEN a.exit_code = 0 THEN 1 ELSE 0 END) AS succeeded,
        SUM(CASE WHEN a.exit_code > 0 THEN 1 ELSE 0 END) AS failed,
        SUM(CASE WHEN a.finished_at IS NOT NULL THEN a.finished_at - a.started_at ELSE 0 END) AS duration
      FROM attempts a JOIN jobs j ON j.id = a.job_id
      WHERE j.project = ? GROUP BY a.worker ORDER BY a.worker ASC
    `).all(actor.project);
  }
}
