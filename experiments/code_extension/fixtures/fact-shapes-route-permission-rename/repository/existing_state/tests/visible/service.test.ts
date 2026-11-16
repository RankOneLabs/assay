import { describe, expect, test } from "bun:test";
import { fixture, admin, reader, writer, outsider, expectError } from "./helpers.ts";
import { createApp } from "../../src/app.ts";
import { loadConfig } from "../../src/config.ts";
import { SessionService } from "../../stage/state.ts";


describe("job service through Hono", () => {
  test("creates, reads, patches and moves a persisted job", async () => {
    using f = fixture();
    const created = await f.request("POST", "/jobs", {
      id: "first",
      title: "  First job  ",
      owner: "owner",
      project: "project",
    });
    expect(created.status).toBe(201);
    expect(created.headers.get("location")).toBe("/jobs/first");
    expect(await created.json()).toMatchObject({
      id: "first", title: "First job", stage: "queued", revision: 1,
    });
    const read = await f.request("GET", "/jobs/first", undefined, reader);
    expect(read.status).toBe(200);
    expect(read.headers.get("etag")).toBe('"1"');
    const patched = await f.request("PATCH", "/jobs/first", {
      title: "Updated job", expectedRevision: 1,
    });
    expect(await patched.json()).toMatchObject({ title: "Updated job", revision: 2 });
    const moved = await f.request("POST", "/jobs/first/stage", {
      stage: "active", expectedRevision: 2, reason: "work started",
    });
    expect(await moved.json()).toMatchObject({ stage: "active", revision: 3 });
    const history = await f.request("GET", "/jobs/first/events");
    const events = await history.json() as { action: string }[];
    expect(events.map(event => event.action)).toEqual([
      "job.created", "job.patched", "job.transitioned",
    ]);
  });

  test("separates read, write and administrative permissions", async () => {
    using f = fixture();
    f.create();
    expect((await f.request("GET", "/jobs/job", undefined, reader)).status).toBe(200);
    await expectError(await f.request("PATCH", "/jobs/job", {
      title: "denied", expectedRevision: 1,
    }, reader), 403);
    expect((await f.request("PATCH", "/jobs/job", {
      title: "allowed", expectedRevision: 1,
    }, writer)).status).toBe(200);
    await expectError(await f.request("GET", "/jobs/job", undefined, writer), 403);
    await expectError(await f.request("POST", "/jobs/job/archive", {
      expectedRevision: 2,
    }, writer), 403);
    expect((await f.request("POST", "/jobs/job/archive", {
      expectedRevision: 2,
    }, admin)).status).toBe(200);
  });

  test("cross-project principals cannot read or mutate a known job id", async () => {
    using f = fixture();
    f.create();
    await expectError(await f.request("GET", "/jobs/job", undefined, outsider), 403);
    await expectError(await f.request("PATCH", "/jobs/job", {
      title: "stolen", expectedRevision: 1,
    }, outsider), 403);
    const listed = await f.request("GET", "/jobs", undefined, outsider);
    expect(await listed.json()).toMatchObject({ items: [], total: 0 });
    expect(f.context.jobRepository.require("job").title).toBe("Job job");
    expect(f.context.eventRepository.count("job")).toBe(1);
  });

  test("requires JSON and rejects malformed or unknown fields", async () => {
    using f = fixture();
    const headers = { "x-principal": "admin", "x-project": "project" };
    await expectError(await f.app.request("/jobs", {
      method: "POST", headers, body: "{}",
    }), 400, "invalid_content_type");
    await expectError(await f.app.request("/jobs", {
      method: "POST",
      headers: { ...headers, "content-type": "application/json" },
      body: "{broken",
    }), 400, "invalid_json");
    await expectError(await f.request("POST", "/jobs", {
      id: "invalid", title: "Test", project: "project", owner: "owner", unexpected: true,
    }), 400, "validation_failed");
    expect(f.context.jobRepository.count()).toBe(0);
  });

  test("does not trust self-asserted permission headers", async () => {
    using f = fixture();
    f.create();
    const response = await f.app.request("/jobs/job", {
      headers: { "x-permission": "case_admin", "x-principal": "stranger", "x-project": "project" },
    });
    await expectError(response, 403, "forbidden");
    expect(f.context.jobRepository.count()).toBe(1);
  });

  test("health requests do not require a principal", async () => {
    using f = fixture();
    const response = await f.app.request("/health");
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ ok: true });
    expect((await f.app.request("/unknown")).status).toBe(404);
  });
});

test("configuration validation happens at construction", () => {
  expect(loadConfig({}).port).toBe(3000);
  expect(loadConfig({ port: "8080" }).port).toBe(8080);
  expect(loadConfig({ maxEvidence: 20 }).maxEvidence).toBe(20);
  expect(() => createApp({ port: 0 })).toThrow();
  expect(() => createApp({ maxJobs: -1 })).toThrow();
  expect(() => createApp({ databasePath: "" })).toThrow();
  expect(() => createApp({ maxBulkJobs: 101 })).toThrow();
  expect(() => createApp({ unknown: true })).toThrow();
});

test("session owner clears running status without changing another session", () => {
  const service = new SessionService();
  expect(service.isBuildRunning("one")).toBe(false);
  service.startBuild("one");
  service.startBuild("two");
  expect(service.isBuildRunning("one")).toBe(true);
  expect(() => service.startBuild("one")).toThrow();
  service.endSession("one");
  expect(service.isBuildRunning("one")).toBe(false);
  expect(service.isBuildRunning("two")).toBe(true);
  service.endSession("two");
  expect(service.isBuildRunning("two")).toBe(false);
});

interface PermissionCase {
  title: string;
  method: string;
  path: string;
  body?: unknown;
  required: "read" | "write" | "admin" | "read-write";
  accepted: number;
}

const routePermissions: PermissionCase[] = [
  {
    title: "job listing",
    method: "GET",
    path: "/jobs",
    required: "read",
    accepted: 200,
  },
  {
    title: "job creation",
    method: "POST",
    path: "/jobs",
    body: { id: "new-job", title: "New", owner: "owner", project: "project" },
    required: "write",
    accepted: 201,
  },
  {
    title: "job lookup",
    method: "GET",
    path: "/jobs/job",
    required: "read",
    accepted: 200,
  },
  {
    title: "metadata patch",
    method: "PATCH",
    path: "/jobs/job",
    body: { title: "Changed", expectedRevision: 1 },
    required: "write",
    accepted: 200,
  },
  {
    title: "primary stage operation",
    method: "POST",
    path: "/jobs/job/stage",
    body: { stage: "active", expectedRevision: 1, reason: "start" },
    required: "write",
    accepted: 200,
  },
  {
    title: "peer stage operation",
    method: "POST",
    path: "/jobs/job/stage/peer",
    body: { stage: "active", expectedRevision: 1, reason: "start" },
    required: "write",
    accepted: 200,
  },
  {
    title: "archive",
    method: "POST",
    path: "/jobs/job/archive",
    body: { expectedRevision: 1 },
    required: "admin",
    accepted: 200,
  },
  {
    title: "restore precondition",
    method: "POST",
    path: "/jobs/job/restore",
    body: { expectedRevision: 1 },
    required: "admin",
    accepted: 409,
  },
  {
    title: "event history",
    method: "GET",
    path: "/jobs/job/events",
    required: "read",
    accepted: 200,
  },
  {
    title: "job timeline",
    method: "GET",
    path: "/jobs/job/timeline",
    required: "read",
    accepted: 200,
  },
  {
    title: "job bundle",
    method: "GET",
    path: "/jobs/job/bundle",
    required: "read",
    accepted: 200,
  },
  {
    title: "evidence listing",
    method: "GET",
    path: "/jobs/job/evidence",
    required: "read",
    accepted: 200,
  },
  {
    title: "primary evidence attachment",
    method: "POST",
    path: "/jobs/job/evidence",
    body: { id: "new-proof", kind: "image", title: "Image", content: "Image", author: "writer" },
    required: "write",
    accepted: 201,
  },
  {
    title: "peer evidence attachment",
    method: "POST",
    path: "/jobs/job/evidence/peer",
    body: { id: "new-proof", kind: "image", title: "Image", content: "Image", author: "writer" },
    required: "write",
    accepted: 201,
  },
  {
    title: "evidence lookup",
    method: "GET",
    path: "/jobs/job/evidence/proof",
    required: "read",
    accepted: 200,
  },
  {
    title: "evidence content",
    method: "GET",
    path: "/jobs/job/evidence/proof/content",
    required: "read",
    accepted: 200,
  },
  {
    title: "evidence patch",
    method: "PATCH",
    path: "/jobs/job/evidence/proof",
    body: { title: "Changed proof", expectedRevision: 1 },
    required: "write",
    accepted: 200,
  },
  {
    title: "evidence deletion",
    method: "DELETE",
    path: "/jobs/job/evidence/proof",
    body: { expectedRevision: 1 },
    required: "write",
    accepted: 200,
  },
  {
    title: "evidence manifest",
    method: "GET",
    path: "/jobs/job/evidence/manifest",
    required: "read",
    accepted: 200,
  },
  {
    title: "evidence verification",
    method: "GET",
    path: "/jobs/job/evidence/verify",
    required: "read",
    accepted: 200,
  },
  {
    title: "evidence search",
    method: "POST",
    path: "/jobs/job/evidence/search",
    body: { query: "Content" },
    required: "read",
    accepted: 200,
  },
  {
    title: "build start",
    method: "POST",
    path: "/jobs/job/builds",
    body: { id: "attempt", sessionId: "session", worker: "worker", expectedRevision: 1 },
    required: "write",
    accepted: 201,
  },
  {
    title: "build history",
    method: "GET",
    path: "/jobs/job/builds",
    required: "read",
    accepted: 200,
  },
  {
    title: "build summary",
    method: "GET",
    path: "/jobs/job/builds/summary",
    required: "read",
    accepted: 200,
  },
  {
    title: "build recovery precondition",
    method: "POST",
    path: "/jobs/job/builds/recover",
    body: { reason: "recover" },
    required: "admin",
    accepted: 409,
  },
  {
    title: "grant listing",
    method: "GET",
    path: "/grants/reader",
    required: "admin",
    accepted: 200,
  },
  {
    title: "primary grant operation",
    method: "POST",
    path: "/grants",
    body: { principal: "new-user", project: "project", permission: "case_read" },
    required: "admin",
    accepted: 201,
  },
  {
    title: "peer grant operation",
    method: "POST",
    path: "/grants/peer",
    body: { principal: "new-user", project: "project", permission: "case_read" },
    required: "admin",
    accepted: 201,
  },
  {
    title: "grant revocation",
    method: "DELETE",
    path: "/grants",
    body: { principal: "reader", project: "project", permission: "case_read" },
    required: "admin",
    accepted: 200,
  },
  {
    title: "project summary",
    method: "GET",
    path: "/reports/summary",
    required: "read",
    accepted: 200,
  },
  {
    title: "worker outcomes",
    method: "GET",
    path: "/reports/outcomes",
    required: "read",
    accepted: 200,
  },
  {
    title: "activity report",
    method: "GET",
    path: "/reports/activity",
    required: "read",
    accepted: 200,
  },
  {
    title: "owner workloads",
    method: "GET",
    path: "/reports/workloads",
    required: "read",
    accepted: 200,
  },
  {
    title: "project JSON export",
    method: "GET",
    path: "/exports",
    required: "read",
    accepted: 200,
  },
  {
    title: "project CSV export",
    method: "GET",
    path: "/exports/csv",
    required: "read",
    accepted: 200,
  },
  {
    title: "bulk archival",
    method: "POST",
    path: "/maintenance/archive",
    body: { ids: ["job"], reason: "reviewed" },
    required: "admin",
    accepted: 200,
  },
  {
    title: "purge",
    method: "POST",
    path: "/maintenance/purge?before=0&limit=1",
    required: "admin",
    accepted: 200,
  },
  {
    title: "integrity report",
    method: "GET",
    path: "/maintenance/integrity",
    required: "admin",
    accepted: 200,
  },
  {
    title: "project execution plan",
    method: "GET",
    path: "/planning",
    required: "read",
    accepted: 200,
  },
  {
    title: "ready queue",
    method: "GET",
    path: "/planning/ready",
    required: "read",
    accepted: 200,
  },
  {
    title: "dependency creation",
    method: "POST",
    path: "/jobs/target/dependencies",
    body: { requiresId: "job" },
    required: "write",
    accepted: 201,
  },
  {
    title: "dependency impact",
    method: "GET",
    path: "/jobs/job/impact",
    required: "read",
    accepted: 200,
  },
  {
    title: "job blockers",
    method: "GET",
    path: "/jobs/job/blockers",
    required: "read",
    accepted: 200,
  },
  {
    title: "dispatch capacity",
    method: "GET",
    path: "/dispatch/capacity",
    required: "read",
    accepted: 200,
  },
  {
    title: "dispatch live attempts",
    method: "GET",
    path: "/dispatch/running",
    required: "read",
    accepted: 200,
  },
  {
    title: "queue dispatch",
    method: "POST",
    path: "/dispatch",
    body: { id: "attempt", sessionId: "session", worker: "worker" },
    required: "read-write",
    accepted: 201,
  },
  {
    title: "job clone",
    method: "POST",
    path: "/jobs/job/clone",
    body: { id: "copy" },
    required: "read-write",
    accepted: 201,
  },
  {
    title: "job comparison",
    method: "GET",
    path: "/jobs/job/compare/target",
    required: "read",
    accepted: 200,
  },
  {
    title: "bulk job patch",
    method: "POST",
    path: "/jobs/bulk/patch",
    body: { reason: "batch", changes: [{ id: "job", patch: { title: "New", expectedRevision: 1 } }] },
    required: "write",
    accepted: 200,
  },
  {
    title: "bulk stage transition",
    method: "POST",
    path: "/jobs/bulk/stage",
    body: { changes: [{ id: "job", transition: { stage: "active", expectedRevision: 1, reason: "start" } }] },
    required: "write",
    accepted: 200,
  },
  {
    title: "bulk evidence attachment",
    method: "POST",
    path: "/jobs/job/evidence/bulk",
    body: [{ id: "new-proof", kind: "image", title: "Image", content: "Image", author: "author" }],
    required: "write",
    accepted: 201,
  },
  {
    title: "bulk evidence removal",
    method: "DELETE",
    path: "/jobs/job/evidence/bulk",
    body: [{ id: "proof", expectedRevision: 1 }],
    required: "write",
    accepted: 200,
  },
  {
    title: "evidence copy",
    method: "POST",
    path: "/jobs/job/evidence/proof/copy",
    body: { jobId: "target", id: "copy" },
    required: "read-write",
    accepted: 201,
  },
  {
    title: "evidence comparison",
    method: "GET",
    path: "/jobs/job/evidence/compare/target",
    required: "read",
    accepted: 200,
  },
  {
    title: "bulk grant",
    method: "POST",
    path: "/grants/bulk",
    body: [{ principal: "new-user", permission: "case_read" }],
    required: "admin",
    accepted: 201,
  },
  {
    title: "bulk revoke",
    method: "DELETE",
    path: "/grants/bulk",
    body: [{ principal: "reader", permission: "case_read" }],
    required: "admin",
    accepted: 200,
  },
  {
    title: "evidence preference lookup",
    method: "GET",
    path: "/preferences/evidence-kind",
    required: "write",
    accepted: 200,
  },
  {
    title: "evidence preference selection",
    method: "PUT",
    path: "/preferences/evidence-kind",
    body: { kind: "image" },
    required: "write",
    accepted: 204,
  },
  {
    title: "evidence preference clearing",
    method: "DELETE",
    path: "/preferences/evidence-kind",
    required: "write",
    accepted: 204,
  },
  {
    title: "permission preference lookup",
    method: "GET",
    path: "/preferences/permission",
    required: "admin",
    accepted: 200,
  },
  {
    title: "permission preference selection",
    method: "PUT",
    path: "/preferences/permission",
    body: { permission: "case_read" },
    required: "admin",
    accepted: 204,
  },
  {
    title: "permission preference clearing",
    method: "DELETE",
    path: "/preferences/permission",
    required: "admin",
    accepted: 204,
  },
  {
    title: "default grant precondition",
    method: "POST",
    path: "/grants/default/new-user",
    required: "admin",
    accepted: 409,
  },
];

describe("HTTP permission matrix", () => {
  for (const route of routePermissions) {
    for (const actor of [admin, reader, writer]) {
      test(`${route.title}: ${actor.id}`, async () => {
        using f = fixture();
        f.create();
        f.create("target");
        f.attach("proof");
        const allowed = actor.id === admin.id ||
          (actor.id === reader.id && route.required === "read") ||
          (actor.id === writer.id && route.required === "write");
        const response = await f.request(route.method, route.path, route.body, actor);
        expect(response.status).toBe(allowed ? route.accepted : 403);
        if (!allowed) {
          expect(f.context.jobRepository.require("job").revision).toBe(1);
          expect(f.context.evidenceRepository.require("proof").revision).toBe(1);
          expect(f.context.eventRepository.count("job")).toBe(2);
        }
      });
    }
  }
});

describe("HTTP error boundaries", () => {
  test("invalid bodies do not leak SQLite errors or stack traces", async () => {
    using f = fixture();
    const response = await f.request("POST", "/jobs", {
      id: "bad/key", title: "Invalid", owner: "owner", project: "project",
    });
    expect(response.status).toBe(400);
    const text = await response.text();
    expect(text).toContain("validation_failed");
    expect(text).not.toContain("sqlite");
    expect(text).not.toContain("at ServiceContext");
    expect(f.context.jobRepository.count()).toBe(0);
  });

  test("unexpected database errors are opaque but roll back business writes", async () => {
    using f = fixture();
    f.context.db.exec(`
      CREATE TRIGGER fail_request BEFORE INSERT ON job_events
      BEGIN SELECT RAISE(ABORT, 'private diagnostic'); END;
    `);
    const response = await f.request("POST", "/jobs", {
      id: "job", title: "Job", owner: "owner", project: "project",
    });
    expect(response.status).toBe(500);
    expect(await response.json()).toEqual({ error: "internal_error" });
    expect(f.context.jobRepository.get("job")).toBeNull();
  });

  test("validation distinguishes a malformed body from an invalid domain payload", async () => {
    using f = fixture();
    const headers = {
      "content-type": "application/json",
      "x-principal": "admin",
      "x-project": "project",
    };
    const malformed = await f.app.request("/jobs", {
      method: "POST", headers, body: "{",
    });
    expect(malformed.status).toBe(400);
    expect(await malformed.json()).toMatchObject({ error: "invalid_json" });
    const primitive = await f.app.request("/jobs", {
      method: "POST", headers, body: "42",
    });
    expect(primitive.status).toBe(400);
    expect(await primitive.json()).toMatchObject({ error: "validation_failed" });
  });

  test("missing principal, missing project and invalid ids are rejected", async () => {
    using f = fixture();
    f.create();
    const anonymous = await f.app.request("/jobs/job");
    expect(anonymous.status).toBe(400);
    const noProject = await f.app.request("/jobs/job", { headers: { "x-principal": "admin" } });
    expect(noProject.status).toBe(400);
    const invalid = await f.app.request("/jobs/job", {
      headers: { "x-principal": "bad/id", "x-project": "project" },
    });
    expect(invalid.status).toBe(400);
    expect(f.context.eventRepository.count("job")).toBe(1);
  });

  test("known missing resources return typed not-found errors", async () => {
    using f = fixture();
    await expectError(await f.request("GET", "/jobs/missing"), 404, "not_found");
    f.create();
    await expectError(await f.request("GET", "/jobs/job/evidence/missing"), 404, "not_found");
    await expectError(await f.request("GET", "/jobs/job/builds/missing/output"), 404, "not_found");
    expect(f.context.jobRepository.count()).toBe(1);
  });

  test("unsupported routes use the application not-found response", async () => {
    using f = fixture();
    const response = await f.request("POST", "/not-a-route", {});
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ error: "not_found" });
    expect(f.context.jobRepository.count()).toBe(0);
  });

  test("query parsing rejects invalid event cursors and oversized pages", async () => {
    using f = fixture();
    f.create();
    await expectError(await f.request("GET", "/jobs/job/events?after=-1"), 400);
    await expectError(await f.request("GET", "/jobs/job/events?limit=101"), 400);
    await expectError(await f.request("GET", "/jobs?limit=0"), 400);
    await expectError(await f.request("GET", "/jobs?stage=triaged"), 400);
    await expectError(await f.request("GET", "/jobs?unexpected=value"), 400);
    expect(f.context.eventRepository.count("job")).toBe(1);
  });

  test("UTF-8 evidence size violations have a typed size error", async () => {
    using f = fixture({ maxEvidenceBytes: 3 });
    f.create();
    const response = await f.request("POST", "/jobs/job/evidence", {
      id: "oversized", kind: "document", title: "Proof", content: "éé", author: "author",
    });
    await expectError(response, 413, "limit_exceeded");
    expect(f.context.evidenceRepository.count("job")).toBe(0);
    expect(f.context.eventRepository.count("job")).toBe(1);
  });

  test("ETags advance only after committed job changes", async () => {
    using f = fixture();
    f.create();
    const original = await f.request("GET", "/jobs/job");
    expect(original.headers.get("etag")).toBe('"1"');
    const stale = await f.request("PATCH", "/jobs/job", { title: "Stale", expectedRevision: 2 });
    await expectError(stale, 409);
    expect((await f.request("GET", "/jobs/job")).headers.get("etag")).toBe('"1"');
    expect((await f.request("PATCH", "/jobs/job", { title: "Changed", expectedRevision: 1 })).status).toBe(200);
    expect((await f.request("GET", "/jobs/job")).headers.get("etag")).toBe('"2"');
  });
});

describe("JSON media type boundary", () => {
  test("application/json with a charset is accepted", async () => {
    using f = fixture();
    const response = await f.app.request("/jobs", {
      method: "POST",
      headers: {
        "content-type": "application/json; charset=utf-8",
        "x-principal": "admin",
        "x-project": "project",
      },
      body: JSON.stringify({ id: "job", title: "Job", owner: "owner", project: "project" }),
    });
    expect(response.status).toBe(201);
    expect(f.context.jobRepository.count()).toBe(1);
  });

  test("a misleading JSON prefix is refused before parsing or writing", async () => {
    using f = fixture();
    const response = await f.app.request("/jobs", {
      method: "POST",
      headers: {
        "content-type": "application/jsonp",
        "x-principal": "admin",
        "x-project": "project",
      },
      body: JSON.stringify({ id: "job", title: "Job", owner: "owner", project: "project" }),
    });
    await expectError(response, 400, "invalid_content_type");
    expect(f.context.jobRepository.count()).toBe(0);
  });
});

test("session starts reject empty ids and ending an absent session is idempotent", () => {
  const sessions = new SessionService();
  expect(() => sessions.startBuild("")).toThrow("empty session");
  expect(() => sessions.startBuild("  ")).toThrow("empty session");
  sessions.endSession("absent");
  sessions.endSession("absent");
  expect(sessions.isBuildRunning("absent")).toBe(false);
  sessions.startBuild("reusable");
  sessions.endSession("reusable");
  sessions.startBuild("reusable");
  expect(sessions.isBuildRunning("reusable")).toBe(true);
});
