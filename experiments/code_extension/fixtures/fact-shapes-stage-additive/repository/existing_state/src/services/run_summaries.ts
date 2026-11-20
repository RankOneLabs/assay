import type { Database } from "bun:sqlite";
import { values as stages } from "../../stage/types.ts";
import type { Run } from "../domain/models.ts";
import { JobRepository } from "../repositories/jobs.ts";
import { AttemptRepository } from "../repositories/attempts.ts";

/** What a run's jobs and their attempts add up to. */
export interface RunSummary {
  runId: string;
  jobs: number;
  stages: Record<string, number>;
  attempts: number;
  passed: number;
  failed: number;
  workers: string[];
  buildTime: number;
}

/**
 * Builds run summaries. A summary reads every attempt of every job in the run, so a
 * finished run keeps a stored summary.
 */
export class RunSummaries {
  constructor(
    private readonly db: Database,
    private readonly jobs: JobRepository,
    private readonly attempts: AttemptRepository,
    private readonly now: () => number,
  ) {}

  read(run: Run): RunSummary {
    const saved = this.stored(run.id);
    if (saved !== null) return saved.summary;
    const summary = this.build(run.id);
    if (run.state.status === "finished") this.keep(run, summary);
    return summary;
  }

  private build(runId: string): RunSummary {
    const jobs = this.jobs.inRun(runId);
    const counts: Record<string, number> = Object.fromEntries(stages.map(stage => [stage, 0]));
    const attempts = jobs.flatMap(job => this.attempts.list(job.id));
    for (const job of jobs) counts[job.stage] = (counts[job.stage] ?? 0) + 1;
    return {
      runId,
      jobs: jobs.length,
      stages: counts,
      attempts: attempts.length,
      passed: attempts.filter(attempt => attempt.exitCode === 0).length,
      failed: attempts.filter(attempt => attempt.exitCode !== null && attempt.exitCode > 0).length,
      workers: [...new Set(attempts.map(attempt => attempt.worker))].sort(),
      buildTime: attempts.reduce((sum, attempt) =>
        sum + (attempt.finishedAt === null ? 0 : attempt.finishedAt - attempt.startedAt), 0),
    };
  }

  private stored(runId: string): { revision: number; summary: RunSummary } | null {
    const row = this.db.query<{ revision: number; summary: string }, [string]>(
      "SELECT revision, summary FROM run_summaries WHERE run_id = ?",
    ).get(runId);
    return row ? { revision: row.revision, summary: JSON.parse(row.summary) as RunSummary } : null;
  }

  private keep(run: Run, summary: RunSummary): void {
    this.db.query(`
      INSERT INTO run_summaries (run_id, revision, summary, stored_at) VALUES (?, ?, ?, ?)
      ON CONFLICT (run_id) DO UPDATE SET
        revision = excluded.revision, summary = excluded.summary, stored_at = excluded.stored_at
    `).run(run.id, run.revision, JSON.stringify(summary), this.now());
  }
}
