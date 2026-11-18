import { vocabularyStore as canonicalStore } from "../../src/vocabulary.ts";
function canonical(feature: string): never { return canonicalStore.values(feature)[0] as never; }
import { describe, expect, test } from "bun:test";
import { fixture, admin, reader, writer, outsider } from "./helpers.ts";
import { values as stages } from "../../stage/types.ts";
import { values as kinds } from "../../evidence_kind/types.ts";

describe("project reports", () => {
  test("empty summaries retain all vocabulary categories with zero counts", () => {
    using f = fixture();
    const summary = f.context.reports.summary(reader);
    expect(summary.total).toBe(0);
    expect(summary.archived).toBe(0);
    expect(summary.workloads).toEqual([]);
    expect(summary.stages.map(item => item.stage)).toEqual([...stages]);
    expect(summary.evidence.map(item => item.kind)).toEqual([...kinds]);
    expect(summary.stages.every(item => item.count === 0)).toBe(true);
    expect(summary.evidence.every(item => item.count === 0 && item.bytes === 0)).toBe(true);
  });

  test("stage counts use persisted transitions and exclude archived jobs", () => {
    using f = fixture();
    f.create(canonical("stage"));
    f.create("active");
    f.create("archived");
    f.context.jobs.transition(admin, "active", {
      stage: "active", expectedRevision: 1, reason: "start",
    });
    f.context.jobs.archive(admin, "archived", { expectedRevision: 1 });
    const summary = f.context.reports.summary(reader);
    expect(summary.total).toBe(3);
    expect(summary.archived).toBe(1);
    expect(summary.stages.find(item => item.stage === canonical("stage"))?.count).toBe(1);
    expect(summary.stages.find(item => item.stage === "active")?.count).toBe(1);
    expect(summary.stages.find(item => item.stage === "complete")?.count).toBe(0);
  });

  test("evidence byte totals include multibyte text and separate kinds", () => {
    using f = fixture();
    f.create();
    f.attach(canonical("evidence_kind"), "job", { kind: canonical("evidence_kind"), content: "éé" });
    f.attach("image", "job", { kind: "image", content: "image-bytes" });
    const summary = f.context.reports.summary(reader);
    expect(summary.evidence.find(item => item.kind === canonical("evidence_kind"))).toMatchObject({ count: 1, bytes: 4 });
    expect(summary.evidence.find(item => item.kind === "image")).toMatchObject({ count: 1, bytes: 11 });
    expect(summary.evidence.find(item => item.kind === "testimony")).toMatchObject({ count: 0, bytes: 0 });
  });

  test("workloads group by owner, sum priority and exclude archives", () => {
    using f = fixture();
    f.create("sam-1", { owner: "sam", priority: 3 });
    f.create("sam-2", { owner: "sam", priority: 7 });
    f.create("pat", { owner: "pat", priority: 9 });
    f.create("old", { owner: "sam", priority: 99 });
    f.context.jobs.archive(admin, "old", { expectedRevision: 1 });
    expect(f.context.reports.workloads(reader)).toEqual([
      { owner: "sam", jobs: 2, priority: 10 },
      { owner: "pat", jobs: 1, priority: 9 },
    ]);
  });

  test("workload ties use owner names for deterministic ordering", () => {
    using f = fixture();
    f.create("z", { owner: "z-owner", priority: 5 });
    f.create("a", { owner: "a-owner", priority: 2 });
    expect(f.context.reports.workloads(reader).map(item => item.owner)).toEqual(["a-owner", "z-owner"]);
  });

  test("activity groups events by action and respects a lower time bound", () => {
    using f = fixture();
    const first = f.create("first");
    const second = f.create("second");
    f.context.jobs.patch(admin, "first", { title: "changed", expectedRevision: 1 });
    const all = f.context.reports.activity(reader, 0, 100);
    expect(all.find(item => item.action === "job.created")?.count).toBe(2);
    expect(all.find(item => item.action === "job.patched")?.count).toBe(1);
    const newer = f.context.reports.activity(reader, second.createdAt, 100);
    expect(newer.find(item => item.action === "job.created")?.count).toBe(1);
    expect(newer.every(item => item.first > first.createdAt)).toBe(true);
    expect(f.context.reports.activity(reader, 100000, 100)).toEqual([]);
  });

  test("outcome report separates successful and failed attempts by worker", () => {
    using f = fixture();
    f.create();
    f.context.builds.start(admin, "job", {
      id: "first", sessionId: "one", worker: "worker", expectedRevision: 1,
    });
    f.context.builds.finish(admin, "job", { sessionId: "one", exitCode: 1, output: "retry" });
    f.context.builds.start(admin, "job", {
      id: "second", sessionId: "two", worker: "worker", expectedRevision: 3,
    });
    f.context.builds.finish(admin, "job", { sessionId: "two", exitCode: 0, output: "done" });
    const outcomes = f.context.reports.outcomes(reader);
    expect(outcomes).toHaveLength(1);
    expect(outcomes[0]).toMatchObject({ worker: "worker", attempts: 2, succeeded: 1, failed: 1 });
    expect(outcomes[0]!.duration).toBeGreaterThan(0);
  });

  test("unfinished attempts do not count as successes or failures", () => {
    using f = fixture();
    f.create();
    f.context.builds.start(admin, "job", {
      id: "attempt", sessionId: "session", worker: "worker", expectedRevision: 1,
    });
    expect(f.context.reports.outcomes(reader)).toEqual([
      { worker: "worker", attempts: 1, succeeded: 0, failed: 0, duration: 0 },
    ]);
    f.context.sessions.endSession("session");
    expect(f.context.reports.outcomes(reader)[0]?.failed).toBe(0);
  });

  test("all reports scope joins to the principal project", () => {
    using f = fixture();
    f.create();
    f.attach();
    const summary = f.context.reports.summary(outsider);
    expect(summary.total).toBe(0);
    expect(summary.evidence.every(item => item.count === 0)).toBe(true);
    expect(f.context.reports.workloads(outsider)).toEqual([]);
    expect(f.context.reports.activity(outsider, 0, 100)).toEqual([]);
    expect(f.context.reports.outcomes(outsider)).toEqual([]);
  });

  test("reports require read permission even when the result would be empty", () => {
    using f = fixture();
    expect(() => f.context.reports.summary(writer)).toThrow("permission");
    expect(() => f.context.reports.workloads(writer)).toThrow("permission");
    expect(() => f.context.reports.activity(writer, 0, 100)).toThrow("permission");
    expect(() => f.context.reports.outcomes(writer)).toThrow("permission");
  });

  test("report HTTP endpoints expose the same scoped results as services", async () => {
    using f = fixture();
    f.create();
    const summary = await f.request("GET", "/reports/summary", undefined, reader);
    expect(summary.status).toBe(200);
    expect(await summary.json()).toEqual(f.context.reports.summary(reader));
    const workloads = await f.request("GET", "/reports/workloads", undefined, reader);
    expect(await workloads.json()).toEqual(f.context.reports.workloads(reader));
    const outcomes = await f.request("GET", "/reports/outcomes", undefined, reader);
    expect(await outcomes.json()).toEqual([]);
    const activity = await f.request("GET", "/reports/activity?since=0&limit=1", undefined, reader);
    expect(await activity.json()).toHaveLength(1);
  });
});
