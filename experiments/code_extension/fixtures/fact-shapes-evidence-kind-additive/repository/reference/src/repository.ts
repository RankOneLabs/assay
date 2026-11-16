import type { Database } from "bun:sqlite";
import type { Stage } from "../stage/types.ts";
import type { EvidenceKind } from "../evidence_kind/types.ts";
import type { RoutePermission } from "../route_permission/types.ts";
interface Values { stage: Stage; evidence_kind: EvidenceKind; route_permission: RoutePermission }
export class ValueRepository<K extends keyof Values> {
  constructor(private readonly db: Database, private readonly feature: K) {
    if (!["stage", "evidence_kind", "route_permission"].includes(feature)) throw new Error("bad table");
  }
  insert(id: string, value: Values[K]): void {
    this.db.query(`INSERT INTO ${this.feature}_values (id, value) VALUES (?, ?)`).run(id, value);
  }
  get(id: string): { id: string; value: Values[K] } | null {
    return this.db.query<{ id: string; value: Values[K] }, [string]>(
      `SELECT id, value FROM ${this.feature}_values WHERE id = ?`,
    ).get(id);
  }
  remove(id: string): void { this.db.query(`DELETE FROM ${this.feature}_values WHERE id = ?`).run(id); }
}
