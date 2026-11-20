import type { Database } from "bun:sqlite";
import { values as stages, type Stage } from "../../stage/types.ts";
import type { Page, Principal, StageCount } from "../domain/models.ts";
import { readAccess } from "../domain/access_levels.ts";
import { dayMs, type ProjectSettings } from "../domain/settings.ts";
import { stageLabel } from "../presentation/labels.ts";
import { SettingsRepository } from "../repositories/settings.ts";
import { page } from "../repositories/paging.ts";
import { AccessService } from "./access.ts";

/** Completed jobs are done: they are not work in progress and cannot go stale. */
const finished: Stage = "complete";
const staleSample = 10;

export interface OwnerLoad {
  owner: string;
  open: number;
  limit: number;
  overLimit: boolean;
}

export interface EvidenceUsage {
  items: number;
  bytes: number;
  quota: number;
  remaining: number;
  overQuota: boolean;
}

export interface StaleJob {
  id: string;
  title: string;
  owner: string;
  stage: Stage;
  updatedAt: number;
  idleDays: number;
}

export interface UsageReport {
  generatedAt: number;
  settings: ProjectSettings;
  owners: OwnerLoad[];
  ownersOverLimit: string[];
  evidence: EvidenceUsage;
  stages: StageCount[];
  stale: Page<StaleJob>;
}

/** Measures a project against its settings; open means neither archived nor complete. */
export class UsageService {
  constructor(
    private readonly db: Database,
    private readonly settings: SettingsRepository,
    private readonly access: AccessService,
    private readonly now: () => number,
  ) {}

  report(actor: Principal): UsageReport {
    this.access.require(actor, readAccess);
    const now = this.now();
    const settings = this.settings.get(actor.project);
    const owners = this.db.query<{ owner: string; open: number }, [string, string]>(`
      SELECT owner, COUNT(*) AS open FROM jobs
      WHERE project = ? AND archived_at IS NULL AND stage != ?
      GROUP BY owner ORDER BY open DESC, owner ASC
    `).all(actor.project, finished).map(row => ({
      ...row,
      limit: settings.wipLimit,
      overLimit: row.open > settings.wipLimit,
    }));
    const evidence = this.db.query<{ items: number; bytes: number }, [string]>(`
      SELECT COUNT(*) AS items, COALESCE(SUM(length(CAST(e.content AS BLOB))), 0) AS bytes
      FROM evidence e JOIN jobs j ON j.id = e.job_id WHERE j.project = ?
    `).get(actor.project)!;
    const counts = new Map(this.db.query<{ stage: Stage; count: number }, [string]>(`
      SELECT stage, COUNT(*) AS count FROM jobs
      WHERE project = ? AND archived_at IS NULL GROUP BY stage
    `).all(actor.project).map(row => [row.stage, row.count]));
    return {
      generatedAt: now,
      settings,
      owners,
      ownersOverLimit: owners.filter(owner => owner.overLimit).map(owner => owner.owner),
      evidence: {
        ...evidence,
        quota: settings.evidenceQuotaBytes,
        remaining: Math.max(0, settings.evidenceQuotaBytes - evidence.bytes),
        overQuota: evidence.bytes > settings.evidenceQuotaBytes,
      },
      stages: stages.map(stage => ({ stage, label: stageLabel(stage), count: counts.get(stage) ?? 0 })),
      stale: this.staleJobs(actor.project, settings, now, staleSample, 0),
    };
  }

  stale(actor: Principal, limit: number, offset: number): Page<StaleJob> {
    this.access.require(actor, readAccess);
    return this.staleJobs(actor.project, this.settings.get(actor.project), this.now(), limit, offset);
  }

  /** Open jobs whose last update is more than the threshold ago, longest idle first. */
  private staleJobs(project: string, settings: ProjectSettings, now: number, limit: number, offset: number) {
    const cutoff = now - settings.staleAfterDays * dayMs;
    const where = "project = ? AND archived_at IS NULL AND stage != ? AND updated_at < ?";
    const total = this.db.query<{ count: number }, [string, string, number]>(
      `SELECT COUNT(*) AS count FROM jobs WHERE ${where}`,
    ).get(project, finished, cutoff)!.count;
    const rows = this.db.query<Omit<StaleJob, "idleDays">, [string, string, number, number, number]>(`
      SELECT id, title, owner, stage, updated_at AS updatedAt FROM jobs WHERE ${where}
      ORDER BY updated_at ASC, id ASC LIMIT ? OFFSET ?
    `).all(project, finished, cutoff, limit, offset);
    const items = rows.map(row => ({ ...row, idleDays: Math.floor((now - row.updatedAt) / dayMs) }));
    return page(items, total, limit, offset);
  }
}
