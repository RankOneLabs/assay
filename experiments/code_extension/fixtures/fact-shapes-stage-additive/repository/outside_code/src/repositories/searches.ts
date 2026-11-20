import type { Database } from "bun:sqlite";
import type { Page } from "../domain/models.ts";
import { page } from "./paging.ts";
import { conflict, missing, revisionMatches } from "../domain/errors.ts";

export interface SavedSearch {
  id: string;
  project: string;
  owner: string;
  name: string;
  query: string;
  shared: boolean;
  revision: number;
  createdAt: number;
  updatedAt: number;
}

type SavedSearchRow = Omit<SavedSearch, "shared"> & { shared: number };

const columns = `id, project, owner, name, query, shared, revision,
  created_at AS createdAt, updated_at AS updatedAt FROM saved_searches`;

function decode(row: SavedSearchRow): SavedSearch {
  return { ...row, shared: row.shared === 1 };
}

export class SavedSearchRepository {
  constructor(private readonly db: Database) {}

  get(id: string): SavedSearch | null {
    const row = this.db.query<SavedSearchRow, [string]>(`SELECT ${columns} WHERE id = ?`).get(id);
    return row ? decode(row) : null;
  }

  require(id: string): SavedSearch {
    return this.get(id) ?? missing("saved search", id);
  }

  countOwned(project: string, owner: string): number {
    return this.db.query<{ count: number }, [string, string]>(
      "SELECT COUNT(*) AS count FROM saved_searches WHERE project = ? AND owner = ?",
    ).get(project, owner)!.count;
  }

  create(input: Omit<SavedSearch, "revision" | "createdAt" | "updatedAt">, now: number): SavedSearch {
    if (this.get(input.id)) conflict("saved search id already exists");
    this.db.query(`
      INSERT INTO saved_searches (id, project, owner, name, query, shared, revision, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
    `).run(input.id, input.project, input.owner, input.name, input.query, input.shared ? 1 : 0, now, now);
    return this.require(input.id);
  }

  update(
    id: string,
    change: { name: string; query: string; shared: boolean },
    expectedRevision: number,
    now: number,
  ): SavedSearch {
    const current = this.require(id);
    revisionMatches(current.revision, expectedRevision);
    this.db.query(`
      UPDATE saved_searches SET name = ?, query = ?, shared = ?, revision = revision + 1, updated_at = ?
      WHERE id = ? AND revision = ?
    `).run(change.name, change.query, change.shared ? 1 : 0, now, id, expectedRevision);
    return this.require(id);
  }

  delete(id: string, expectedRevision: number): SavedSearch {
    const current = this.require(id);
    revisionMatches(current.revision, expectedRevision);
    this.db.query("DELETE FROM saved_searches WHERE id = ? AND revision = ?").run(id, expectedRevision);
    return current;
  }

  /** The principal's own searches and every search shared in the project, by name. */
  visible(project: string, owner: string, limit: number, offset: number): Page<SavedSearch> {
    const total = this.db.query<{ count: number }, [string, string]>(`
      SELECT COUNT(*) AS count FROM saved_searches WHERE project = ? AND (owner = ? OR shared = 1)
    `).get(project, owner)!.count;
    const rows = this.db.query<SavedSearchRow, [string, string, number, number]>(`
      SELECT ${columns} WHERE project = ? AND (owner = ? OR shared = 1)
      ORDER BY name ASC, owner ASC, id ASC LIMIT ? OFFSET ?
    `).all(project, owner, limit, offset);
    return page(rows.map(decode), total, limit, offset);
  }
}
