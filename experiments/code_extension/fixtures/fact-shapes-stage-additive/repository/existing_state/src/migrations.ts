import { Database } from "bun:sqlite";
export interface Migration { id: string; sql: string }
export async function discoverMigrations(root: string): Promise<Migration[]> {
  const migrations: Migration[] = [];
  for (const path of new Bun.Glob("db/migrations/[0-9]*.sql").scanSync({ cwd: root })) {
    migrations.push({ id: path, sql: await Bun.file(`${root}/${path}`).text() });
  }
  return migrations.sort((a, b) => a.id.localeCompare(b.id));
}
export function applyMigrations(db: Database, migrations: readonly Migration[]): void {
  db.exec("CREATE TABLE IF NOT EXISTS schema_migrations (id TEXT PRIMARY KEY)");
  for (const migration of [...migrations].sort((a,b) => a.id.localeCompare(b.id))) {
    if (db.query("SELECT id FROM schema_migrations WHERE id = ?").get(migration.id)) continue;
    db.transaction(() => {
      db.exec(migration.sql);
      db.query("INSERT INTO schema_migrations (id) VALUES (?)").run(migration.id);
    })();
  }
}
