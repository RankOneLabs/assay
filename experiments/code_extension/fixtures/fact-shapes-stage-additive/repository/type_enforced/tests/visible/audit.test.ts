import { describe, expect, test } from "bun:test";
import { fixture, admin, reader, writer, outsider, expectError } from "./helpers.ts";
import { values as stages } from "../../stage/types.ts";

const day = 86_400_000;

/** Two jobs in the project, one moved to active, plus a job in another project. */
function seeded() {
  const f = fixture();
  f.create("first");
  f.create("second");
  f.context.jobs.transition(admin, "first", { stage: "active", expectedRevision: 1, reason: "start" });
  f.context.jobs.patch(writer, "second", { priority: 5, expectedRevision: 1 });
  f.context.jobs.create(outsider, { id: "foreign", title: "Foreign", owner: "owner", project: "other" });
  return f;
}

describe("audit queries", () => {
  test("events stay inside the caller's project and filter by actor, action, job and time", () => {
    using f = seeded();
    const all = f.context.audit.events(admin, {});
    expect(all.items.map(event => [event.jobId, event.action])).toEqual([
      ["first", "job.created"],
      ["second", "job.created"],
      ["first", "job.transitioned"],
      ["second", "job.patched"],
    ]);
    expect(all.nextCursor).toBeNull();
    expect(all.items[2]!.detail).toMatchObject({ to: "active", reason: "start" });
    expect(f.context.audit.events(admin, { actor: "writer" }).items.map(event => event.action)).toEqual(["job.patched"]);
    expect(f.context.audit.events(admin, { action: "job.c" }).items).toHaveLength(2);
    expect(f.context.audit.events(admin, { jobId: "second" }).items).toHaveLength(2);
    expect(f.context.audit.events(admin, { jobId: "foreign" }).items).toEqual([]);
    const [, second, third] = all.items;
    const window = f.context.audit.events(admin, { from: String(second!.createdAt), to: String(third!.createdAt + 1) });
    expect(window.items.map(event => event.sequence)).toEqual([second!.sequence, third!.sequence]);
    expect(f.context.audit.events(outsider, {}).items.map(event => event.jobId)).toEqual(["foreign"]);
  });

  test("action prefixes match literally rather than as LIKE patterns", () => {
    using f = fixture();
    f.create();
    f.context.eventRepository.append("job", "jobxcreated", "admin", {}, 5000);
    expect(f.context.audit.events(admin, { action: "job_" }).items).toEqual([]);
    expect(f.context.audit.events(admin, { action: "job" }).items).toHaveLength(2);
  });

  test("cursor pages are stable while new events arrive", () => {
    using f = seeded();
    const first = f.context.audit.events(admin, { limit: "3" });
    expect(first.items).toHaveLength(3);
    expect(first.nextCursor).toBe(first.items[2]!.sequence);
    f.context.jobs.patch(admin, "first", { priority: 9, expectedRevision: 2 });
    const second = f.context.audit.events(admin, { limit: "3", after: String(first.nextCursor) });
    expect(second.items.map(event => event.action)).toEqual(["job.patched", "job.patched"]);
    expect(second.nextCursor).toBeNull();
    expect(new Set([...first.items, ...second.items].map(event => event.sequence)).size).toBe(5);
  });

  test("queries need case_admin and well-formed filters", () => {
    using f = seeded();
    expect(() => f.context.audit.events(reader, {})).toThrow("permission");
    expect(() => f.context.audit.events(writer, {})).toThrow("permission");
    expect(() => f.context.audit.summary(reader, { by: "actor" })).toThrow("permission");
    expect(() => f.context.audit.events(admin, { from: "10", to: "10" })).toThrow("earlier");
    expect(() => f.context.audit.events(admin, { action: "Job%" })).toThrow();
    expect(() => f.context.audit.events(admin, { limit: "201" })).toThrow();
    expect(() => f.context.audit.events(admin, { stage: "active" })).toThrow();
    expect(() => f.context.audit.summary(admin, { by: "owner" })).toThrow();
  });

  test("summaries group by actor, action and UTC day", () => {
    using f = seeded();
    f.context.eventRepository.append("second", "job.reviewed", "auditor", {}, 2 * day + 5);
    expect(f.context.audit.summary(admin, { by: "actor" })).toMatchObject({
      by: "actor",
      total: 5,
      groups: [
        { key: "admin", count: 3, jobs: 2 },
        { key: "auditor", count: 1, jobs: 1 },
        { key: "writer", count: 1, jobs: 1 },
      ],
    });
    const actions = f.context.audit.summary(admin, { by: "action", action: "job." });
    expect(actions.groups.map(group => [group.key, group.count])).toEqual([
      ["job.created", 2], ["job.patched", 1], ["job.reviewed", 1], ["job.transitioned", 1],
    ]);
    const days = f.context.audit.summary(admin, { by: "day" });
    expect(days.groups.map(group => [group.key, group.count])).toEqual([["1970-01-01", 4], ["1970-01-03", 1]]);
    expect(days.groups[1]).toMatchObject({ first: 2 * day + 5, last: 2 * day + 5 });
  });

  test("stage history spans follow each transition and total time per stage", () => {
    using f = fixture();
    const job = f.create();
    f.context.jobs.transition(admin, "job", { stage: "active", expectedRevision: 1, reason: "start" });
    f.context.jobs.transition(admin, "job", { stage: "complete", expectedRevision: 2, reason: "done" });
    const history = f.context.audit.stages(admin, "job");
    expect(history).toMatchObject({ jobId: "job", stage: "complete", consistent: true, transitions: 2 });
    expect(history.spans.map(span => [span.stage, span.reason])).toEqual([
      [job.stage, null], ["active", "start"], ["complete", "done"],
    ]);
    expect(history.spans[0]!.leftAt).toBe(history.spans[1]!.enteredAt);
    expect(history.spans[2]!.leftAt).toBeNull();
    expect(Object.keys(history.totals)).toEqual([...stages]);
    expect(history.totals.active).toBe(history.spans[1]!.durationMs);
    expect(() => f.context.audit.stages(reader, "job")).toThrow("permission");
    expect(() => f.context.audit.stages(outsider, "job")).toThrow("another project");
  });

  test("a transition that skips its recorded source marks the history inconsistent", () => {
    using f = fixture();
    f.create();
    f.context.eventRepository.append("job", "job.transitioned", "admin", { from: "active", to: "complete", reason: "x" }, 5000);
    const history = f.context.audit.stages(admin, "job");
    expect(history.consistent).toBe(false);
    expect(f.context.audit.dwell(admin).inconsistent).toEqual(["job"]);
  });

  test("dwell totals cover every stage and count jobs currently in each", () => {
    using f = seeded();
    const archived = f.context.jobs.archive(admin, "second", { expectedRevision: 2 });
    const dwell = f.context.audit.dwell(admin);
    expect(dwell.jobs).toBe(2);
    expect(dwell.stages.map(item => item.stage)).toEqual([...stages]);
    const active = dwell.stages.find(item => item.stage === "active")!;
    expect(active).toMatchObject({ label: "In progress", entries: 1, current: 1 });
    const initial = dwell.stages.find(item => item.stage === archived.stage)!;
    expect(initial.entries).toBe(2);
    expect(f.context.audit.stages(admin, "second").spans[0]!.durationMs).toBe(archived.archivedAt! - archived.createdAt);
  });
});

describe("audit routes", () => {
  test("events, summary and stage routes require an administrator", async () => {
    using f = seeded();
    const page = await f.request("GET", "/audit/events?limit=2&actor=admin");
    expect(await page.json()).toMatchObject({ items: [{ jobId: "first" }, { jobId: "second" }] });
    const summary = await f.request("GET", "/audit/summary?by=action");
    expect((await summary.json() as { total: number }).total).toBe(4);
    const stagesResponse = await f.request("GET", "/audit/jobs/first/stages");
    expect(await stagesResponse.json()).toMatchObject({ stage: "active", transitions: 1 });
    expect((await f.request("GET", "/audit/stages")).status).toBe(200);
    await expectError(await f.request("GET", "/audit/events", undefined, reader), 403, "forbidden");
    await expectError(await f.request("GET", "/audit/events?to=abc"), 400, "validation_failed");
    await expectError(await f.request("GET", "/audit/jobs/missing/stages"), 404, "not_found");
  });

  test("export streams NDJSON with a continuation cursor", async () => {
    using f = seeded();
    const response = await f.request("GET", "/audit/export?limit=3");
    expect(response.headers.get("content-type")).toStartWith("application/x-ndjson");
    expect(response.headers.get("x-audit-count")).toBe("3");
    const lines = (await response.text()).split("\n");
    expect(lines.at(-1)).toBe("");
    const events = lines.slice(0, -1).map(line => JSON.parse(line) as { sequence: number; action: string });
    expect(events.map(event => event.action)).toEqual(["job.created", "job.created", "job.transitioned"]);
    expect(response.headers.get("x-audit-next-cursor")).toBe(String(events[2]!.sequence));
    const rest = await f.request("GET", `/audit/export?after=${events[2]!.sequence}`);
    expect(rest.headers.get("x-audit-next-cursor")).toBeNull();
    expect((await rest.text()).trim().split("\n")).toHaveLength(1);
    await expectError(await f.request("GET", "/audit/export?limit=5001"), 400, "validation_failed");
  });
});
