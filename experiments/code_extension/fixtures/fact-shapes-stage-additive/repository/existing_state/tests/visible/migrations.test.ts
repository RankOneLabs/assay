import { vocabularyStore as canonicalStore } from "../../src/vocabulary.ts";
function canonical(feature: string): never { return canonicalStore.values(feature)[0] as never; }
import { describe, expect, test } from "bun:test";
import { Database } from "bun:sqlite";
import { applyMigrations, discoverMigrations } from "../../src/migrations.ts";
import { initializeDatabase, baseMigrations } from "../../src/database.ts";
import { ValueRepository } from "../../src/repository.ts";

const root = `${import.meta.dir}/../..`;

describe("ordered SQLite migrations", () => {
  test("discovery returns every lookup table migration in path order", async () => {
    const migrations = await discoverMigrations(root);
    const ids = migrations.map(migration => migration.id);
    expect(ids).toEqual([...ids].sort());
    expect(ids).toEqual(baseMigrations().map(migration => migration.id));
    for (const feature of ["stage", "evidence_kind", "route_permission"]) {
      const initial = migrations.find(migration => migration.sql.includes(`CREATE TABLE ${feature}_values`))!;
      expect(initial.id).toStartWith("db/migrations/");
      expect(initial.sql).toContain("CHECK");
      expect(initial.sql).toContain("PRIMARY KEY");
    }
  });

  test("fresh in-memory databases accept the stable vocabulary values", async () => {
    using db = new Database(":memory:");
    applyMigrations(db, await discoverMigrations(root));
    const stageRepository = new ValueRepository(db, "stage");
    for (const stage of ["active", "complete"] as const) {
      stageRepository.insert(stage, stage);
      expect(stageRepository.get(stage)).toEqual({ id: stage, value: stage });
    }
    const kindRepository = new ValueRepository(db, "evidence_kind");
    for (const kind of ["image", "testimony"] as const) {
      kindRepository.insert(kind, kind);
      expect(kindRepository.get(kind)).toEqual({ id: kind, value: kind });
    }
    const permissionRepository = new ValueRepository(db, "route_permission");
    for (const permission of ["case_write", "case_admin"] as const) {
      permissionRepository.insert(permission, permission);
      expect(permissionRepository.get(permission)).toEqual({ id: permission, value: permission });
    }
  });

  test("CHECK constraints enforce the selected SQL holder when present", async () => {
    using db = new Database(":memory:");
    const migrations = await discoverMigrations(root);
    applyMigrations(db, migrations);
    for (const feature of ["stage", "evidence_kind", "route_permission"]) {
      // The effective table definition, whichever migration last set it.
      const table = db.query<{ sql: string }, [string]>("SELECT sql FROM sqlite_master WHERE name = ?")
        .get(`${feature}_values`)!;
      const insert = () => db.query(`INSERT INTO ${feature}_values VALUES (?, ?)`).run("future", "future_value");
      if (/value IN/.test(table.sql)) expect(insert).toThrow(/CHECK constraint failed/);
      else { insert(); expect(db.query(`SELECT value FROM ${feature}_values WHERE id = 'future'`).get()).toEqual({ value: "future_value" }); }
    }
  });

  test("migrations are applied once even when requested in reverse order", async () => {
    using db = new Database(":memory:");
    const migrations = await discoverMigrations(root);
    applyMigrations(db, [...migrations].reverse());
    applyMigrations(db, migrations);
    const rows = db.query<{ id: string }, []>("SELECT id FROM schema_migrations ORDER BY id").all();
    expect(rows.map(row => row.id)).toEqual(migrations.map(migration => migration.id));
  });

  test("a failing migration rolls back its schema and journal entry", () => {
    using db = new Database(":memory:");
    expect(() => applyMigrations(db, [{
      id: "broken",
      sql: "CREATE TABLE transient (id TEXT); INSERT INTO nonexistent VALUES (1);",
    }])).toThrow();
    expect(db.query("SELECT name FROM sqlite_master WHERE name = 'transient'").get()).toBeNull();
    expect(db.query("SELECT id FROM schema_migrations WHERE id = 'broken'").get()).toBeNull();
    applyMigrations(db, [{ id: "broken", sql: "CREATE TABLE transient (id TEXT);" }]);
    expect(db.query("SELECT name FROM sqlite_master WHERE name = 'transient'").get()).not.toBeNull();
  });

  test("successful earlier migrations survive a later migration failure", () => {
    using db = new Database(":memory:");
    expect(() => applyMigrations(db, [
      { id: "001", sql: "CREATE TABLE first (id TEXT PRIMARY KEY);" },
      { id: "002", sql: "INSERT INTO missing VALUES (1);" },
    ])).toThrow();
    expect(db.query("SELECT id FROM schema_migrations WHERE id = '001'").get()).not.toBeNull();
    expect(db.query("SELECT id FROM schema_migrations WHERE id = '002'").get()).toBeNull();
    db.query("INSERT INTO first (id) VALUES (?)").run("persisted");
    expect(db.query("SELECT id FROM first").get()).toEqual({ id: "persisted" });
  });

  for (const [feature, values, future] of [
    ["stage", ["active", "complete"], "unsupported_future"],
    ["evidence_kind", ["image", "testimony"], "unsupported_future"],
    ["route_permission", ["case_write", "case_admin"], "unsupported_future"],
  ] as const) {
    test(`${feature} admits the new value after a widening migration`, async () => {
      using db = new Database(":memory:");
      applyMigrations(db, await discoverMigrations(root));
      db.query(`INSERT INTO ${feature}_values VALUES (?, ?)`).run("existing", values[0]);
      const sql = `
        ALTER TABLE ${feature}_values RENAME TO previous_values;
        CREATE TABLE ${feature}_values (
          id TEXT PRIMARY KEY,
          value TEXT NOT NULL UNIQUE CHECK (value IN (${[...values, future].map(v => `'${v}'`).join(", ")}))
        );
        INSERT INTO ${feature}_values SELECT * FROM previous_values;
        DROP TABLE previous_values;
      `;
      applyMigrations(db, [{ id: `db/migrations/900_widen_${feature}.sql`, sql }]);
      db.query(`INSERT INTO ${feature}_values VALUES (?, ?)`).run("new", future);
      expect(db.query(`SELECT value FROM ${feature}_values WHERE id = 'new'`).get()).toEqual({ value: future });
      expect(db.query(`SELECT value FROM ${feature}_values WHERE id = 'existing'`).get()).toEqual({ value: values[0] });
    });
  }

  test("business foreign keys reject values bypassing typed service code", () => {
    using db = new Database(":memory:");
    initializeDatabase(db, baseMigrations());
    expect(() => db.query(`
      INSERT INTO stage_retention (project, stage, days, updated_by, updated_at)
      VALUES ('project', 'unsupported_future', 30, 'admin', 0)
    `).run()).toThrow(/FOREIGN KEY/);
    expect(() => db.query(`
      INSERT INTO grants (principal, permission, project, granted_by, created_at)
      VALUES ('bad', 'unsupported_future', 'project', 'admin', 0)
    `).run()).toThrow(/FOREIGN KEY/);
    expect(() => db.query(`
      INSERT INTO attempts (id, job_id, session_id, worker, started_at, output)
      VALUES ('orphan', 'missing', 'session', 'worker', 0, '')
    `).run()).toThrow(/FOREIGN KEY/);
    expect(() => db.query(`
      INSERT INTO job_events (job_id, action, actor, detail, created_at)
      VALUES ('missing', 'job.created', 'admin', '{}', 0)
    `).run()).toThrow(/FOREIGN KEY/);
  });

  test("database initialization preserves business data across repeated calls", () => {
    using db = new Database(":memory:");
    initializeDatabase(db, baseMigrations());
    db.query(`
      INSERT INTO jobs (id, title, description, stage, priority, owner, project, revision, created_at, updated_at)
      VALUES ('job', 'Persisted', '', 'active', 0, 'owner', 'project', 1, 0, 0)
    `).run();
    const seeded = db.query("SELECT COUNT(*) AS count FROM stage_values").get();
    initializeDatabase(db, baseMigrations());
    expect(db.query("SELECT title FROM jobs WHERE id = 'job'").get()).toEqual({ title: "Persisted" });
    expect(db.query("SELECT COUNT(*) AS count FROM stage_values").get()).toEqual(seeded);
    expect(db.query("SELECT COUNT(*) AS count FROM stage_values WHERE value IN ('active', 'complete')").get())
      .toEqual({ count: 2 });
  });
});

describe("business table constraints", () => {
  test("job fields cannot bypass numeric or null constraints through SQL", () => {
    using db = new Database(":memory:");
    initializeDatabase(db, baseMigrations());
    const insert = db.query(`
      INSERT INTO jobs (id, title, description, stage, priority, owner, project, revision, created_at, updated_at)
      VALUES (?, ?, '', 'active', ?, 'owner', 'project', ?, 0, 0)
    `);
    expect(() => insert.run("priority", "Title", -1, 1)).toThrow(/CHECK/);
    expect(() => insert.run("revision", "Title", 0, 0)).toThrow(/CHECK/);
    expect(() => insert.run("null-title", null, 0, 1)).toThrow(/NOT NULL/);
    expect(db.query("SELECT COUNT(*) AS count FROM jobs").get()).toEqual({ count: 0 });
  });

  test("evidence cannot refer to a nonexistent job or an unknown kind", () => {
    using db = new Database(":memory:");
    initializeDatabase(db, baseMigrations());
    const insert = db.query(`
      INSERT INTO evidence (id, job_id, kind, title, content, checksum, author, revision, created_at, updated_at)
      VALUES (?, ?, ?, 'Proof', 'content', 'digest', 'author', 1, 0, 0)
    `);
    expect(() => insert.run("orphan", "missing", "testimony")).toThrow(/FOREIGN KEY/);
    db.query(`
      INSERT INTO jobs (id, title, description, stage, priority, owner, project, revision, created_at, updated_at)
      VALUES ('job', 'Title', '', 'active', 0, 'owner', 'project', 1, 0, 0)
    `).run();
    expect(() => insert.run("bad-kind", "job", "unsupported_future")).toThrow(/FOREIGN KEY/);
    insert.run("valid", "job", "testimony");
    expect(() => insert.run("duplicate-digest", "job", "image")).toThrow(/UNIQUE/);
    expect(db.query("SELECT id FROM evidence").all()).toEqual([{ id: "valid" }]);
  });

  test("attempts enforce unique session identities and bounded exit codes", () => {
    using db = new Database(":memory:");
    initializeDatabase(db, baseMigrations());
    db.query(`
      INSERT INTO jobs (id, title, description, stage, priority, owner, project, revision, created_at, updated_at)
      VALUES ('job', 'Title', '', 'active', 0, 'owner', 'project', 1, 0, 0)
    `).run();
    db.query(`
      INSERT INTO attempts (id, job_id, session_id, worker, started_at, output)
      VALUES ('first', 'job', 'session', 'worker', 0, '')
    `).run();
    expect(() => db.query(`
      INSERT INTO attempts (id, job_id, session_id, worker, started_at, output)
      VALUES ('second', 'job', 'session', 'worker', 0, '')
    `).run()).toThrow(/UNIQUE/);
    expect(() => db.query("UPDATE attempts SET exit_code = -1 WHERE id = 'first'").run()).toThrow(/CHECK/);
    expect(() => db.query("UPDATE attempts SET exit_code = 256 WHERE id = 'first'").run()).toThrow(/CHECK/);
    expect(db.query("SELECT exit_code FROM attempts WHERE id = 'first'").get()).toEqual({ exit_code: null });
  });

  test("dependency rows cannot refer to missing jobs or the same job twice", () => {
    using db = new Database(":memory:");
    initializeDatabase(db, baseMigrations());
    db.query(`
      INSERT INTO jobs (id, title, description, stage, priority, owner, project, revision, created_at, updated_at)
      VALUES ('job', 'Title', '', 'active', 0, 'owner', 'project', 1, 0, 0)
    `).run();
    const insert = db.query("INSERT INTO job_dependencies VALUES (?, ?, 'actor', 0)");
    expect(() => insert.run("job", "job")).toThrow(/CHECK/);
    expect(() => insert.run("job", "missing")).toThrow(/FOREIGN KEY/);
    expect(db.query("SELECT COUNT(*) AS count FROM job_dependencies").get()).toEqual({ count: 0 });
  });
});

describe("durable service restart", () => {
  test("job, evidence and grant owners survive reopen while session state stays ephemeral", async () => {
    const { ServiceContext } = await import("../../src/context.ts");
    const { values } = await import("../../route_permission/types.ts");
    const path = `/tmp/fact-service-${crypto.randomUUID()}.sqlite`;
    const principal = { id: "admin", project: "project" };
    try {
      {
        using context = new ServiceContext({ databasePath: path }, () => 1000);
        for (const permission of values.slice(0, 3)) context.grantRepository.grant(principal, permission, "bootstrap", 0);
        context.jobs.create(principal, { id: "job", title: "Persistent", owner: "owner", project: "project" });
        context.evidence.attach(principal, "job", {
          id: "proof", kind: "image", title: "Proof", content: "Persistent evidence", author: "author",
        });
        context.builds.start(principal, "job", {
          id: "attempt", sessionId: "session", worker: "worker", expectedRevision: 1,
        });
        expect(context.sessions.isBuildRunning("session")).toBe(true);
        expect(context.jobRepository.require("job").stage).toBe("active");
      }
      {
        using reopened = new ServiceContext({ databasePath: path }, () => 2000);
        expect(reopened.jobs.get(principal, "job").title).toBe("Persistent");
        expect(reopened.evidence.get(principal, "job", "proof").content).toBe("Persistent evidence");
        expect(reopened.sessions.isBuildRunning("session")).toBe(false);
        expect(reopened.builds.list(principal, "job")[0]?.running).toBe(false);
        expect(reopened.attemptRepository.require("attempt").finishedAt).toBeNull();
        const recovery = reopened.builds.recover(principal, "job", "restart recovery");
        expect(recovery.job.stage).toBe(canonical("stage"));
        expect(recovery.attempts[0]?.exitCode).toBe(255);
        expect(reopened.eventRepository.count("job")).toBe(4);
      }
    } finally {
      await Bun.file(path).delete();
    }
  });

  test("reopening a service does not duplicate vocabulary rows or migrations", async () => {
    const { ServiceContext } = await import("../../src/context.ts");
    const path = `/tmp/fact-journal-${crypto.randomUUID()}.sqlite`;
    const counts: unknown[] = [];
    try {
      for (let iteration = 0; iteration < 3; iteration++) {
        using context = new ServiceContext({ databasePath: path });
        expect(context.db.query("SELECT COUNT(*) AS count FROM schema_migrations").get()).toEqual({ count: baseMigrations().length + 1 });
        counts.push(["stage", "evidence_kind", "route_permission"].map(feature =>
          context.db.query(`SELECT COUNT(*) AS count FROM ${feature}_values`).get()));
      }
      expect(counts[1]).toEqual(counts[0]);
      expect(counts[2]).toEqual(counts[0]);
    } finally {
      await Bun.file(path).delete();
    }
  });

  test("independent in-memory contexts cannot observe each other's writes", async () => {
    const { ServiceContext } = await import("../../src/context.ts");
    using left = new ServiceContext();
    using right = new ServiceContext();
    left.grantRepository.grant({ id: "user", project: "project" }, "case_write", "bootstrap", 0);
    expect(left.grantRepository.has({ id: "user", project: "project" }, "case_write")).toBe(true);
    expect(right.grantRepository.has({ id: "user", project: "project" }, "case_write")).toBe(false);
    left.sessions.startBuild("left-session");
    expect(left.sessions.isBuildRunning("left-session")).toBe(true);
    expect(right.sessions.isBuildRunning("left-session")).toBe(false);
  });
});

describe("migration path identity", () => {
  test("equal basenames in different feature directories do not collide", () => {
    using db = new Database(":memory:");
    applyMigrations(db, [
      { id: "second/001_create.sql", sql: "CREATE TABLE second_table (id TEXT PRIMARY KEY);" },
      { id: "first/001_create.sql", sql: "CREATE TABLE first_table (id TEXT PRIMARY KEY);" },
    ]);
    const journal = db.query<{ id: string }, []>("SELECT id FROM schema_migrations ORDER BY id").all();
    expect(journal).toEqual([
      { id: "first/001_create.sql" },
      { id: "second/001_create.sql" },
    ]);
    db.query("INSERT INTO first_table VALUES ('first')").run();
    db.query("INSERT INTO second_table VALUES ('second')").run();
    expect(db.query("SELECT id FROM first_table").get()).toEqual({ id: "first" });
    expect(db.query("SELECT id FROM second_table").get()).toEqual({ id: "second" });
  });

  test("lexicographic ordering is independent of caller array order", () => {
    using db = new Database(":memory:");
    applyMigrations(db, [
      { id: "feature/003_index.sql", sql: "CREATE INDEX record_value ON records(value);" },
      { id: "feature/001_create.sql", sql: "CREATE TABLE records (id TEXT PRIMARY KEY);" },
      { id: "feature/002_column.sql", sql: "ALTER TABLE records ADD COLUMN value TEXT NOT NULL DEFAULT '';" },
    ]);
    db.query("INSERT INTO records (id, value) VALUES ('record', 'ordered')").run();
    expect(db.query("SELECT value FROM records WHERE id = 'record'").get()).toEqual({ value: "ordered" });
    expect(db.query("SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'record_value'").get())
      .toEqual({ name: "record_value" });
  });
});
