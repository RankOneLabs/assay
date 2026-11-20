import type { Database } from "bun:sqlite";
import type { Page, Run, RunRollup } from "../domain/models.ts";
import { conflict, missing } from "../domain/errors.ts";
import { runFinishTime } from "../timing/finish_times.ts";
import { page } from "./paging.ts";

interface RunRow {
  id: string;
  project: string;
  title: string;
  state: string;
  status: string;
  finished_at: number | null;
  revision: number;
  created_at: number;
  updated_at: number;
}

function decode(row: RunRow): Run {
  return {
    id: row.id,
    project: row.project,
    title: row.title,
    state: JSON.parse(row.state) as RunRollup,
    finishedAt: row.finished_at,
    revision: row.revision,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

const emptyState: RunRollup = { total: 0, open: 0, done: 0, status: "running" };

export class RunRepository {
  constructor(private readonly db: Database) {}

  get(id: string): Run | null {
    const row = this.db.query<RunRow, [string]>("SELECT * FROM runs WHERE id = ?").get(id);
    return row ? decode(row) : null;
  }

  require(id: string): Run {
    return this.get(id) ?? missing("run", id);
  }

  create(id: string, project: string, title: string, now: number): Run {
    if (this.get(id)) conflict("run id already exists");
    this.db.query(`
      INSERT INTO runs (id, project, title, state, revision, created_at, updated_at)
      VALUES (?, ?, ?, ?, 1, ?, ?)
    `).run(id, project, title, JSON.stringify(emptyState), now, now);
    return this.require(id);
  }

  /** Store a run's roll-up state; every store is a new revision. */
  store(id: string, state: RunRollup, now: number): Run {
    const current = this.require(id);
    const finishedAt = runFinishTime(current.finishedAt, state.status === "finished", now);
    this.db.query(`
      UPDATE runs SET state = ?, finished_at = ?, revision = revision + 1, updated_at = ? WHERE id = ?
    `).run(JSON.stringify(state), finishedAt, now, id);
    return this.require(id);
  }

  /** Runs of a project, oldest first, optionally only those with a stored status. */
  list(project: string, status: string | undefined, limit: number, offset: number): Page<Run> {
    const filter = status === undefined ? "" : "AND status = ?";
    const bindings = status === undefined ? [project] : [project, status];
    const total = this.db.query<{ count: number }, string[]>(
      `SELECT COUNT(*) AS count FROM runs WHERE project = ? ${filter}`,
    ).get(...bindings)!.count;
    const rows = this.db.query<RunRow, (string | number)[]>(`
      SELECT * FROM runs WHERE project = ? ${filter} ORDER BY created_at ASC, id ASC LIMIT ? OFFSET ?
    `).all(...bindings, limit, offset);
    return page(rows.map(decode), total, limit, offset);
  }
}
