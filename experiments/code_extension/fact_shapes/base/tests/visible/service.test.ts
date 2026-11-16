import { describe, expect, test } from "bun:test";
import { Database } from "bun:sqlite";
import { createApp } from "../../src/app.ts";
import { loadConfig } from "../../src/config.ts";
import { stageRoutes, routeStage } from "../../src/routing.ts";
import { routeFor, DEFAULT_ROUTE, validateRegisteredValue } from "../../stage/names.ts";
import { values } from "../../stage/types.ts";
import { values as evidence } from "../../evidence_kind/types.ts";
import { values as permissions } from "../../route_permission/types.ts";
import { edit } from "../../stage/edit.ts";
import { SessionService } from "../../stage/state.ts";
import { StoredEvidenceKind } from "../../evidence_kind/state.ts";
import { StoredRoutePermission } from "../../route_permission/state.ts";
import { applyMigrations, discoverMigrations } from "../../src/migrations.ts";
import { ValueRepository } from "../../src/repository.ts";

const root = `${import.meta.dir}/../..`;

describe("routing and policies", () => {
  test("every stage has an exhaustive route", () => {
    for (const stage of values) expect(routeStage(stage)).toBe(stageRoutes[stage]);
  });
  test("unknown names silently fall back", () => {
    expect(routeFor("unknown")).toBe(DEFAULT_ROUTE);
    expect(routeFor(values[0])).toContain(values[0]);
    expect(validateRegisteredValue("unknown")).toBe(false);
  });
  test("edit applies anchor validation and reference limits", () => {
    expect(edit("job-1", values[0]).value).toBe(values[0]);
    expect(() => edit("bad/key", values[0])).toThrow();
    expect(() => edit("job-1", values[0], 101)).toThrow();
  });
});

describe("HTTP guards", () => {
  for (const path of ["primary", "peer"]) {
    for (const key of ["valid-key", "", "bad/key", "x".repeat(81)]) {
      test(`${path} validates ${JSON.stringify(key)}`, async () => {
        const response = await createApp().request(`/jobs/${path}`, {
          method: "POST",
          headers: { "content-type": "application/json", "x-permission": permissions[1] },
          body: JSON.stringify({ key }),
        });
        expect(response.status).toBe(key === "valid-key" ? 201 : 400);
      });
    }
    test(`${path} requires permission`, async () => {
      const response = await createApp().request(`/jobs/${path}`, {
        method: "POST", body: JSON.stringify({ key: "valid" }),
      });
      expect(response.status).toBe(403);
    });
    test(`${path} calls the limits policy`, async () => {
      const response = await createApp({ maxJobs: 2 }).request(`/jobs/${path}`, {
        method: "POST",
        headers: { "content-type": "application/json", "x-permission": permissions[1] },
        body: JSON.stringify({ key: "valid", count: 3 }),
      });
      expect(response.status).toBe(400);
    });
  }
});

test("config is validated at app construction", () => {
  expect(loadConfig({}).port).toBe(3000);
  expect(loadConfig({ port: "8080" }).port).toBe(8080);
  for (const invalid of [{ port: 0 }, { maxJobs: -1 }, { databasePath: "" }]) {
    expect(() => createApp(invalid)).toThrow();
  }
});

test("session service is the running-build owner", () => {
  const service = new SessionService();
  expect(service.isBuildRunning("one")).toBe(false);
  service.startBuild("one");
  expect(service.isBuildRunning("one")).toBe(true);
  expect(service.isBuildRunning("two")).toBe(false);
  expect(() => service.startBuild("one")).toThrow();
  service.endSession("one");
  expect(service.isBuildRunning("one")).toBe(false);
});

test("selection stores expose the stored source", () => {
  const kinds = new StoredEvidenceKind();
  kinds.set("one", evidence[0]);
  expect(kinds.get("one")).toBe(evidence[0]);
  kinds.remove("one");
  expect(kinds.get("one")).toBeUndefined();
  const grants = new StoredRoutePermission();
  grants.set("one", permissions[0]);
  expect(grants.get("one")).toBe(permissions[0]);
  grants.remove("one");
  expect(grants.get("one")).toBeUndefined();
});

test("ordered migrations enforce every vocabulary and run once", async () => {
  using db = new Database(":memory:");
  const migrations = await discoverMigrations(root);
  applyMigrations(db, migrations);
  applyMigrations(db, migrations);
  for (const [feature, members] of Object.entries({ stage: values, evidence_kind: evidence, route_permission: permissions })) {
    for (const value of members) {
      db.query(`INSERT INTO ${feature}_values (id, value) VALUES (?, ?)`).run(value, value);
    }
    expect(() => db.query(`INSERT INTO ${feature}_values (id, value) VALUES (?, ?)`).run("bad", "undeclared"))
      .toThrow(/CHECK constraint failed/);
  }
  const repository = new ValueRepository(db, "stage");
  repository.insert("fresh", values[0]);
  expect(repository.get("fresh")?.value).toBe(values[0]);
  repository.remove("fresh");
  expect(repository.get("fresh")).toBeNull();
});

test("a subsequent migration can widen a CHECK constraint", async () => {
  using db = new Database(":memory:");
  applyMigrations(db, await discoverMigrations(root));
  const sql = `
    ALTER TABLE stage_values RENAME TO old_stage_values;
    CREATE TABLE stage_values (id TEXT PRIMARY KEY, value TEXT NOT NULL
      CHECK (value IN (${values.map(value => `'${value}'`).join(", ")}, 'triaged')));
    INSERT INTO stage_values SELECT * FROM old_stage_values;
    DROP TABLE old_stage_values;
  `;
  applyMigrations(db, [{ id: "stage/002_widen.sql", sql }]);
  db.query("INSERT INTO stage_values (id, value) VALUES (?, ?)").run("new", "triaged");
  expect(db.query("SELECT value FROM stage_values WHERE id = 'new'").get()).toEqual({ value: "triaged" });
});

test("a valid permission for another operation is refused", async () => {
  const response = await createApp().request("/jobs/primary", {
    method: "POST",
    headers: { "content-type": "application/json", "x-permission": permissions[0] },
    body: JSON.stringify({ key: "valid" }),
  });
  expect(response.status).toBe(403);
});

test("job creation validates the service payload", async () => {
  const response = await createApp().request("/jobs/primary", {
    method: "POST",
    headers: { "content-type": "application/json", "x-permission": permissions[1] },
    body: JSON.stringify({ key: "valid", payload: { title: "" } }),
  });
  expect(response.status).toBe(400);
});
