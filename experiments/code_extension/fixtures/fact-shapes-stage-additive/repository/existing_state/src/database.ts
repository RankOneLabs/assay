import "./bootstrap.ts";
import { Database } from "bun:sqlite";
import { readdirSync, readFileSync } from "node:fs";
import { values as stages } from "../stage/types.ts";
import { values as kinds } from "../evidence_kind/types.ts";
import { values as permissions } from "../route_permission/types.ts";
import { businessSchema } from "./schema.ts";
import { applyMigrations, type Migration } from "./migrations.ts";

/** Apply migrations, then seed each lookup table from the declared types; reopening is idempotent. */
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

/** Read every migration in db/migrations synchronously, in filename order. */
export function baseMigrations(): Migration[] {
  const directory = new URL("../db/migrations/", import.meta.url);
  return readdirSync(directory)
    .filter(name => /^[0-9][^/]*\.sql$/.test(name))
    .sort()
    .map(name => ({ id: `db/migrations/${name}`, sql: readFileSync(new URL(name, directory), "utf8") }));
}
