import type { Database } from "bun:sqlite";
import type { EvidenceKind } from "../../evidence_kind/types.ts";
import type { Evidence, EvidenceCreate, EvidencePatch } from "../domain/models.ts";
import { checksum } from "../domain/checksum.ts";
import { conflict, missing, revisionMatches } from "../domain/errors.ts";

interface EvidenceRow {
  id: string;
  job_id: string;
  kind: EvidenceKind;
  title: string;
  content: string;
  checksum: string;
  author: string;
  revision: number;
  created_at: number;
  updated_at: number;
}

function decode(row: EvidenceRow): Evidence {
  return {
    id: row.id,
    jobId: row.job_id,
    kind: row.kind,
    title: row.title,
    content: row.content,
    checksum: row.checksum,
    author: row.author,
    revision: row.revision,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

export class EvidenceRepository {
  constructor(private readonly db: Database) {}

  get(id: string): Evidence | null {
    const row = this.db.query<EvidenceRow, [string]>("SELECT * FROM evidence WHERE id = ?").get(id);
    return row ? decode(row) : null;
  }

  require(id: string): Evidence {
    return this.get(id) ?? missing("evidence", id);
  }

  list(jobId: string, kind?: EvidenceKind): Evidence[] {
    const rows = kind === undefined
      ? this.db.query<EvidenceRow, [string]>(
        "SELECT * FROM evidence WHERE job_id = ? ORDER BY created_at, id",
      ).all(jobId)
      : this.db.query<EvidenceRow, [string, string]>(
        "SELECT * FROM evidence WHERE job_id = ? AND kind = ? ORDER BY created_at, id",
      ).all(jobId, kind);
    return rows.map(decode);
  }

  duplicate(jobId: string, digest: string, except?: string): Evidence | null {
    const row = this.db.query<EvidenceRow, [string, string, string]>(`
      SELECT * FROM evidence WHERE job_id = ? AND checksum = ? AND id != ?
    `).get(jobId, digest, except ?? "");
    return row ? decode(row) : null;
  }

  count(jobId: string): number {
    return this.db.query<{ count: number }, [string]>(
      "SELECT COUNT(*) AS count FROM evidence WHERE job_id = ?",
    ).get(jobId)!.count;
  }

  create(jobId: string, input: EvidenceCreate, now: number): Evidence {
    if (this.get(input.id)) conflict("evidence id already exists");
    const digest = checksum(input.content);
    if (this.duplicate(jobId, digest)) conflict("evidence content already attached");
    this.db.query(`
      INSERT INTO evidence (
        id, job_id, kind, title, content, checksum, author, revision, created_at, updated_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
    `).run(
      input.id,
      jobId,
      input.kind,
      input.title,
      input.content,
      digest,
      input.author,
      now,
      now,
    );
    return this.require(input.id);
  }

  patch(id: string, patch: EvidencePatch, now: number): Evidence {
    const current = this.require(id);
    revisionMatches(current.revision, patch.expectedRevision);
    const content = patch.content ?? current.content;
    const digest = checksum(content);
    if (this.duplicate(current.jobId, digest, id)) conflict("evidence content already attached");
    this.db.query(`
      UPDATE evidence SET title = ?, content = ?, checksum = ?,
        revision = revision + 1, updated_at = ? WHERE id = ? AND revision = ?
    `).run(patch.title ?? current.title, content, digest, now, id, patch.expectedRevision);
    return this.require(id);
  }

  delete(id: string, revision: number): Evidence {
    const current = this.require(id);
    revisionMatches(current.revision, revision);
    this.db.query("DELETE FROM evidence WHERE id = ? AND revision = ?").run(id, revision);
    return current;
  }
}
