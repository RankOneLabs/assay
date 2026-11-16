import "./bootstrap.ts";
import { Database } from "bun:sqlite";
import { values as stages } from "../stage/types.ts";
import { values as kinds } from "../evidence_kind/types.ts";
import { values as permissions } from "../route_permission/types.ts";
import { businessSchema } from "./schema.ts";
import { applyMigrations, type Migration } from "./migrations.ts";

/** No duplicate CHECK lists: initialization always reads the declared SQL holders. */
export function initializeDatabase(db: Database, migrations: readonly Migration[]): void {
  db.exec("PRAGMA foreign_keys = ON");
  applyMigrations(db, [
    ...migrations,
    { id: "zz_service/001_business", sql: businessSchema },
  ]);
  db.transaction(() => {
    for (const [feature, values] of Object.entries({
      stage: stages,
      evidence_kind: kinds,
      route_permission: permissions,
    })) {
      for (const value of values) {
        db.query(`INSERT OR IGNORE INTO ${feature}_values (id, value) VALUES (?, ?)`).run(value, value);
      }
    }
  })();
}

/** Read the three base migrations synchronously for synchronous app construction. */
export function baseMigrations(): Migration[] {
  return [
    { id: "evidence_kind/001_constraint.sql", sql: evidenceMigration },
    { id: "route_permission/001_constraint.sql", sql: permissionMigration },
    { id: "stage/001_constraint.sql", sql: stageMigration },
  ];
}

import evidenceMigration from "../evidence_kind/001_constraint.sql" with { type: "text" };
import permissionMigration from "../route_permission/001_constraint.sql" with { type: "text" };
import stageMigration from "../stage/001_constraint.sql" with { type: "text" };
