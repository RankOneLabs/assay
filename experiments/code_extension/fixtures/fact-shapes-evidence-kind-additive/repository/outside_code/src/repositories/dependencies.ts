import type { Database } from "bun:sqlite";
import type { Edge } from "../domain/graph.ts";

/** Dependencies are persisted edges, distinct from the stage or session state. */
export class DependencyRepository {
  constructor(private readonly db: Database) {}

  add(jobId: string, requiresId: string, actor: string, now: number): boolean {
    return this.db.query(`
      INSERT OR IGNORE INTO job_dependencies (job_id, requires_id, actor, created_at)
      VALUES (?, ?, ?, ?)
    `).run(jobId, requiresId, actor, now).changes > 0;
  }

  remove(jobId: string, requiresId: string): boolean {
    return this.db.query(`
      DELETE FROM job_dependencies WHERE job_id = ? AND requires_id = ?
    `).run(jobId, requiresId).changes > 0;
  }

  list(project: string): Edge[] {
    return this.db.query<Edge, [string]>(`
      SELECT d.job_id AS jobId, d.requires_id AS requiresId
      FROM job_dependencies d JOIN jobs j ON j.id = d.job_id
      WHERE j.project = ? ORDER BY d.job_id, d.requires_id
    `).all(project);
  }

  requirements(jobId: string): string[] {
    return this.db.query<{ id: string }, [string]>(`
      SELECT requires_id AS id FROM job_dependencies WHERE job_id = ? ORDER BY requires_id
    `).all(jobId).map(row => row.id);
  }

  dependents(jobId: string): string[] {
    return this.db.query<{ id: string }, [string]>(`
      SELECT job_id AS id FROM job_dependencies WHERE requires_id = ? ORDER BY job_id
    `).all(jobId).map(row => row.id);
  }
}
