import { describe, expect, test } from "bun:test";
import { fixture, admin, reader, writer, outsider, originalPermissions, expectError } from "./helpers.ts";
import { ServiceContext } from "../../src/context.ts";
import { readAccess } from "../../src/domain/access_levels.ts";
import { values as stages } from "../../stage/types.ts";

const day = 86_400_000;

/** A context whose clock only moves when the test advances it. */
function clocked() {
  let clock = 10 * day;
  const context = new ServiceContext({}, () => clock);
  for (const permission of originalPermissions) context.grantRepository.grant(admin, permission, "bootstrap", 0);
  context.grantRepository.grant(reader, readAccess, "bootstrap", 0);
  const create = (id: string, owner = "owner") => context.jobs.create(admin, {
    id, title: `Job ${id}`, owner, project: admin.project,
  });
  return { context, create, advance(ms: number) { clock += ms; }, [Symbol.dispose]() { context.close(); } };
}

describe("project settings", () => {
  test("projects start with defaults at revision zero", () => {
    using f = fixture();
    expect(f.context.settings.get(reader)).toEqual({
      project: "project", wipLimit: 5, evidenceQuotaBytes: 10_000_000, defaultReviewOwner: null,
      staleAfterDays: 14, revision: 0, updatedBy: null, updatedAt: null,
    });
    expect(f.context.settings.history(reader, 0, 50)).toEqual([]);
    expect(() => f.context.settings.get(writer)).toThrow("permission required");
  });

  test("changes bump the revision and append only the fields that changed", () => {
    using f = fixture();
    const first = f.context.settings.update(admin, {
      wipLimit: 3, staleAfterDays: 14, defaultReviewOwner: "writer", expectedRevision: 0, reason: "tighten",
    });
    expect(first).toMatchObject({ wipLimit: 3, defaultReviewOwner: "writer", revision: 1, updatedBy: "admin" });
    const second = f.context.settings.update(admin, { defaultReviewOwner: null, expectedRevision: 1 });
    expect(second).toMatchObject({ wipLimit: 3, defaultReviewOwner: null, revision: 2 });
    expect(f.context.settings.update(admin, { wipLimit: 3, expectedRevision: 2 }).revision).toBe(2);
    const history = f.context.settings.history(reader, 0, 50);
    expect(history.map(entry => [entry.revision, entry.actor, entry.reason])).toEqual([
      [1, "admin", "tighten"], [2, "admin", null],
    ]);
    expect(history[0]!.changes).toEqual([
      { field: "wipLimit", before: 5, after: 3 },
      { field: "defaultReviewOwner", before: null, after: "writer" },
    ]);
    expect(f.context.settings.history(reader, 1, 50).map(entry => entry.revision)).toEqual([2]);
    expect(() => f.context.settings.update(admin, { wipLimit: 4, expectedRevision: 1 })).toThrow("revision changed");
    expect(f.context.settings.get(outsider).revision).toBe(0);
  });

  test("invalid settings and non-administrators are refused", () => {
    using f = fixture();
    for (const input of [
      { wipLimit: 0, expectedRevision: 0 },
      { staleAfterDays: 3651, expectedRevision: 0 },
      { evidenceQuotaBytes: 1.5, expectedRevision: 0 },
      { defaultReviewOwner: "bad owner", expectedRevision: 0 },
      { expectedRevision: 0, reason: "nothing" },
      { wipLimit: 2, expectedRevision: 0, color: "red" },
    ]) expect(() => f.context.settings.update(admin, input)).toThrow();
    expect(() => f.context.settings.update(admin, { defaultReviewOwner: "reader", expectedRevision: 0 }))
      .toThrow("needs write permission");
    expect(() => f.context.settings.update(reader, { wipLimit: 2, expectedRevision: 0 })).toThrow("permission required");
    expect(() => f.context.settings.update(writer, { wipLimit: 2, expectedRevision: 0 })).toThrow("permission required");
    expect(f.context.settings.get(admin).revision).toBe(0);
  });

  test("settings routes return an etag and history over HTTP", async () => {
    using f = fixture();
    const changed = await f.request("PATCH", "/settings", { evidenceQuotaBytes: 2048, expectedRevision: 0 });
    expect(await changed.json()).toMatchObject({ evidenceQuotaBytes: 2048, revision: 1 });
    const current = await f.request("GET", "/settings", undefined, reader);
    expect(current.headers.get("etag")).toBe("\"1\"");
    await expectError(await f.request("PATCH", "/settings", { wipLimit: 2, expectedRevision: 0 }), 409, "conflict");
    await expectError(await f.request("PATCH", "/settings", { wipLimit: 2, expectedRevision: 1 }, reader), 403, "forbidden");
    const history = await (await f.request("GET", "/settings/history?after=0&limit=1", undefined, reader)).json();
    expect(history).toEqual([{
      revision: 1, actor: "admin", reason: null, createdAt: expect.any(Number),
      changes: [{ field: "evidenceQuotaBytes", before: 10_000_000, after: 2048 }],
    }]);
  });
});

describe("project usage", () => {
  test("open jobs per owner are measured against the limit", () => {
    using f = fixture();
    f.context.settings.update(admin, { wipLimit: 2, expectedRevision: 0 });
    for (const id of ["sam-1", "sam-2", "sam-3"]) f.create(id, { owner: "sam" });
    f.create("pat-1", { owner: "pat" });
    f.create("done", { owner: "pat" });
    f.create("old", { owner: "pat" });
    f.context.jobs.transition(admin, "done", { stage: "active", expectedRevision: 1, reason: "start" });
    f.context.jobs.transition(admin, "done", { stage: "complete", expectedRevision: 2, reason: "finish" });
    f.context.jobs.archive(admin, "old", { expectedRevision: 1 });
    const report = f.context.usage.report(reader);
    expect(report.owners).toEqual([
      { owner: "sam", open: 3, limit: 2, overLimit: true },
      { owner: "pat", open: 1, limit: 2, overLimit: false },
    ]);
    expect(report.ownersOverLimit).toEqual(["sam"]);
    expect(report.stages.map(item => item.stage)).toEqual([...stages]);
    expect(report.stages.find(item => item.stage === "complete")).toMatchObject({ count: 1, label: "Complete" });
    expect(report.stages.reduce((sum, item) => sum + item.count, 0)).toBe(5);
    expect(() => f.context.usage.report(writer)).toThrow("permission required");
    expect(f.context.usage.report(outsider).owners).toEqual([]);
  });

  test("evidence bytes count UTF-8 content against the quota", () => {
    using f = fixture();
    f.create();
    f.attach("text", "job", { content: "éé" });
    f.attach("picture", "job", { kind: "image", content: "image-bytes" });
    f.context.settings.update(admin, { evidenceQuotaBytes: 12, expectedRevision: 0 });
    expect(f.context.usage.report(reader).evidence).toEqual({
      items: 2, bytes: 15, quota: 12, remaining: 0, overQuota: true,
    });
    f.context.settings.update(admin, { evidenceQuotaBytes: 20, expectedRevision: 1 });
    expect(f.context.usage.report(reader).evidence).toMatchObject({ remaining: 5, overQuota: false });
  });

  test("stale jobs are open jobs idle for longer than the threshold", () => {
    using f = clocked();
    f.create("oldest");
    f.create("done");
    f.context.jobs.transition(admin, "done", { stage: "active", expectedRevision: 1, reason: "start" });
    f.context.jobs.transition(admin, "done", { stage: "complete", expectedRevision: 2, reason: "finish" });
    f.advance(day);
    f.create("older");
    f.create("archived");
    f.context.jobs.archive(admin, "archived", { expectedRevision: 1 });
    f.advance(2 * day);
    f.create("fresh");
    f.context.settings.update(admin, { staleAfterDays: 1, expectedRevision: 0 });
    expect(f.context.usage.stale(reader, 25, 0).items.map(job => job.id)).toEqual(["oldest", "older"]);
    f.advance(day + 1);
    const page = f.context.usage.stale(reader, 2, 0);
    expect(page.items.map(job => [job.id, job.idleDays])).toEqual([["oldest", 4], ["older", 3]]);
    expect(page).toMatchObject({ total: 3, nextOffset: 2 });
    expect(f.context.usage.stale(reader, 2, 2).items.map(job => job.id)).toEqual(["fresh"]);
    f.advance(-day);
    expect(f.context.usage.report(reader).stale.total).toBe(2);
  });

  test("usage routes report over HTTP", async () => {
    using f = fixture();
    f.create();
    const report = await (await f.request("GET", "/usage", undefined, reader)).json() as {
      owners: unknown[]; stale: { total: number }; settings: { revision: number };
    };
    expect(report.owners).toEqual([{ owner: "owner", open: 1, limit: 5, overLimit: false }]);
    expect(report.stale.total).toBe(0);
    expect(report.settings.revision).toBe(0);
    const stale = await f.request("GET", "/usage/stale?limit=10", undefined, reader);
    expect(await stale.json()).toMatchObject({ items: [], total: 0, limit: 10, offset: 0, nextOffset: null });
    await expectError(await f.request("GET", "/usage", undefined, writer), 403, "forbidden");
    await expectError(await f.request("GET", "/usage/stale?limit=500", undefined, reader), 400, "validation_failed");
  });
});
