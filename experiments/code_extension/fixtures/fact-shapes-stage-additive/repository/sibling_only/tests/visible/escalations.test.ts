import { describe, expect, test } from "bun:test";
import { values as stages } from "../../stage/types.ts";
import { fixture, admin, reader, writer, outsider, expectError } from "./helpers.ts";
import { MINUTE_MS, ageInMinutes, deadline, staleBefore } from "../../src/domain/deadlines.ts";
import { readAccess } from "../../src/domain/access_levels.ts";

type Fixture = ReturnType<typeof fixture>;

function rule(overrides: Record<string, unknown> = {}) {
  return { id: "slow-work", stage: "active", maxAgeMinutes: 30, target: reader.id, ...overrides };
}

/** A job moved to active; its update time is the base for every age in these tests. */
function activeJob(f: Fixture, id = "job", overrides: Record<string, unknown> = {}) {
  f.create(id, overrides);
  return f.context.jobs.transition(admin, id, { stage: "active", expectedRevision: 1, reason: "start" });
}

describe("deadline arithmetic", () => {
  test("ages are whole minutes and never negative", () => {
    expect(ageInMinutes(0, 90 * 1000)).toBe(1);
    expect(ageInMinutes(5000, 1000)).toBe(0);
    expect(deadline(1000, 2)).toBe(1000 + 2 * MINUTE_MS);
    expect(staleBefore(10 * MINUTE_MS, 3)).toBe(7 * MINUTE_MS);
  });
});

describe("escalation rules", () => {
  test("administrators create rules with defaults and readers can see them", () => {
    using f = fixture();
    const created = f.context.escalations.createRule(admin, rule());
    expect(created).toMatchObject({
      project: admin.project, stage: "active", minPriority: 0, enabled: true, revision: 1, createdBy: admin.id,
    });
    expect(f.context.escalations.listRules(reader, {})).toEqual([created]);
    expect(f.context.escalations.getRule(reader, "slow-work")).toEqual(created);
    expect(f.context.escalations.listRules(reader, { stage: "complete" })).toEqual([]);
    expect(f.context.escalations.listRules(reader, { enabled: "false" })).toEqual([]);
  });

  test("rule writes need administration and a reachable target", () => {
    using f = fixture();
    expect(() => f.context.escalations.createRule(writer, rule())).toThrow("permission required");
    expect(() => f.context.escalations.createRule(admin, rule({ stage: "unsupported_future" }))).toThrow();
    expect(() => f.context.escalations.createRule(admin, rule({ maxAgeMinutes: 0 }))).toThrow();
    expect(() => f.context.escalations.createRule(admin, rule({ target: "nobody" }))).toThrow("cannot read");
    f.context.escalations.createRule(admin, rule());
    expect(() => f.context.escalations.createRule(admin, rule())).toThrow("already exists");
    expect(() => f.context.escalations.getRule(outsider, "slow-work")).toThrow("another project");
  });

  test("updates keep omitted fields and require the current revision", () => {
    using f = fixture();
    f.context.escalations.createRule(admin, rule({ minPriority: 5 }));
    const updated = f.context.escalations.updateRule(admin, "slow-work", {
      maxAgeMinutes: 60, enabled: false, expectedRevision: 1,
    });
    expect(updated).toMatchObject({ maxAgeMinutes: 60, enabled: false, minPriority: 5, revision: 2 });
    expect(() => f.context.escalations.updateRule(admin, "slow-work", {
      enabled: true, expectedRevision: 1,
    })).toThrow("revision changed");
    expect(() => f.context.escalations.updateRule(admin, "slow-work", { expectedRevision: 2 })).toThrow();
    expect(() => f.context.escalations.updateRule(admin, "slow-work", {
      target: "nobody", expectedRevision: 2,
    })).toThrow("cannot read");
  });
});

describe("escalation evaluation", () => {
  test("opens once per job and rule when the age exceeds the limit", () => {
    using f = fixture();
    const job = activeJob(f);
    f.context.escalations.createRule(admin, rule());
    const atLimit = f.context.escalations.evaluate(admin, { at: job.updatedAt + 30 * MINUTE_MS });
    expect(atLimit.opened).toEqual([]);
    const at = job.updatedAt + 45 * MINUTE_MS;
    const first = f.context.escalations.evaluate(admin, { at });
    expect(first.opened).toHaveLength(1);
    expect(first.opened[0]).toMatchObject({
      jobId: "job", ruleId: "slow-work", stage: "active", target: reader.id,
      ageMinutes: 45, openedAt: at, resolvedAt: null,
    });
    expect(first.truncated).toBe(false);
    const event = f.context.jobs.history(admin, "job").at(-1)!;
    expect(event.action).toBe("job.escalated");
    expect(JSON.parse(event.detail)).toMatchObject({
      ruleId: "slow-work", ageMinutes: 45, deadline: job.updatedAt + 30 * MINUTE_MS,
    });
    expect(f.context.escalations.evaluate(admin, { at: at + MINUTE_MS }).opened).toEqual([]);
  });

  test("priority, archives, disabled rules and other projects are excluded", () => {
    using f = fixture();
    const job = activeJob(f, "low", { priority: 1 });
    activeJob(f, "high", { priority: 9 });
    f.create("parked");
    f.context.jobs.archive(admin, "parked", { expectedRevision: 1 });
    f.context.escalations.createRule(admin, rule({ minPriority: 5 }));
    f.context.escalations.createRule(admin, rule({ id: "off", enabled: false }));
    const at = job.updatedAt + 90 * MINUTE_MS;
    expect(f.context.escalations.evaluate(admin, { at }).opened.map(item => item.jobId)).toEqual(["high"]);
    expect(f.context.escalations.evaluate(outsider, { at }).opened).toEqual([]);
    expect(() => f.context.escalations.evaluate(writer, { at })).toThrow("permission required");
    expect(() => f.context.escalations.evaluate(admin, { at: -1 })).toThrow();
  });

  test("an escalation resolves automatically once its job leaves the stage", () => {
    using f = fixture();
    const job = activeJob(f);
    f.context.escalations.createRule(admin, rule());
    const at = job.updatedAt + 31 * MINUTE_MS;
    const [opened] = f.context.escalations.evaluate(admin, { at }).opened;
    f.context.jobs.transition(admin, "job", { stage: "complete", expectedRevision: 2, reason: "done" });
    const pass = f.context.escalations.evaluate(admin, { at: at + MINUTE_MS });
    expect(pass.resolved).toHaveLength(1);
    expect(pass.resolved[0]).toMatchObject({ id: opened!.id, resolvedBy: admin.id, resolvedAt: at + MINUTE_MS });
    expect(pass.opened).toEqual([]);
    const event = f.context.jobs.history(admin, "job").at(-1)!;
    expect(event.action).toBe("job.escalation_resolved");
    expect(JSON.parse(event.detail)).toMatchObject({ escalationId: opened!.id, automatic: true });
    expect(f.context.escalations.listOpen(reader, {}).total).toBe(0);
  });
});

describe("handling escalations", () => {
  function opened(f: Fixture) {
    const job = activeJob(f);
    f.context.escalations.createRule(admin, rule());
    return f.context.escalations.evaluate(admin, { at: job.updatedAt + 40 * MINUTE_MS }).opened[0]!;
  }

  test("the target acknowledges and another member resolves with a note", () => {
    using f = fixture();
    const escalation = opened(f);
    const acknowledged = f.context.escalations.acknowledge(reader, escalation.id);
    expect(acknowledged.acknowledgedBy).toBe(reader.id);
    expect(() => f.context.escalations.acknowledge(reader, escalation.id)).toThrow("already acknowledged");
    expect(() => f.context.escalations.resolve(writer, escalation.id, { note: "blind" })).toThrow("permission required");
    expect(() => f.context.escalations.resolve(admin, escalation.id, { note: " " })).toThrow();
    const resolved = f.context.escalations.resolve(admin, escalation.id, { note: "picked up" });
    expect(resolved).toMatchObject({ resolvedBy: admin.id, resolution: "picked up" });
    expect(() => f.context.escalations.resolve(admin, escalation.id, { note: "again" })).toThrow("already resolved");
    expect(f.context.jobs.history(admin, "job").slice(-2).map(event => event.action)).toEqual([
      "job.escalation_acknowledged", "job.escalation_resolved",
    ]);
  });

  test("a resolved escalation for a still stale job opens again on the next pass", () => {
    using f = fixture();
    const escalation = opened(f);
    f.context.escalations.resolve(reader, escalation.id, { note: "seen" });
    const again = f.context.escalations.evaluate(admin, { at: escalation.openedAt + MINUTE_MS });
    expect(again.opened).toHaveLength(1);
    expect(again.opened[0]!.id).not.toBe(escalation.id);
  });

  test("non-targets need write access and other projects are refused", () => {
    using f = fixture();
    const escalation = opened(f);
    const viewer = { id: "viewer", project: admin.project };
    f.context.grantRepository.grant(viewer, readAccess, "bootstrap", 0);
    expect(() => f.context.escalations.acknowledge(viewer, escalation.id)).toThrow("permission required");
    expect(() => f.context.escalations.get(outsider, escalation.id)).toThrow("another project");
    expect(() => f.context.escalations.acknowledge(admin, "x")).toThrow();
    expect(() => f.context.escalations.get(reader, 999)).toThrow("not found");
  });

  test("open listings filter and page; the summary covers every stage", () => {
    using f = fixture();
    const first = activeJob(f, "first");
    activeJob(f, "second");
    f.context.escalations.createRule(admin, rule());
    f.context.escalations.createRule(admin, rule({ id: "to-admin", target: admin.id }));
    f.context.escalations.evaluate(admin, { at: first.updatedAt + 60 * MINUTE_MS });
    expect(f.context.escalations.listOpen(reader, {}).total).toBe(4);
    const page = f.context.escalations.listOpen(reader, { target: admin.id, limit: "1" });
    expect(page).toMatchObject({ total: 2, limit: 1, nextOffset: 1 });
    expect(page.items[0]!.ruleId).toBe("to-admin");
    expect(f.context.escalations.listOpen(reader, { ruleId: "slow-work", stage: "complete" }).total).toBe(0);
    expect(() => f.context.escalations.listOpen(reader, { stage: "unsupported_future" })).toThrow();
    f.context.escalations.acknowledge(admin, page.items[0]!.id);
    const summary = f.context.escalations.summary(reader);
    expect(summary.map(item => item.stage)).toEqual([...stages]);
    expect(summary.find(item => item.stage === "active")).toMatchObject({ rules: 2, open: 4, acknowledged: 1 });
    expect(summary.find(item => item.stage === "complete")).toMatchObject({ rules: 0, open: 0, oldestOpenedAt: null });
    expect(() => f.context.escalations.summary(writer)).toThrow("permission required");
  });
});

describe("escalation routes", () => {
  test("rules, evaluation and acknowledgement work over HTTP", async () => {
    using f = fixture();
    const job = activeJob(f);
    const created = await f.request("POST", "/escalation-rules", rule());
    expect(created.status).toBe(201);
    expect(created.headers.get("location")).toBe("/escalation-rules/slow-work");
    await expectError(await f.request("POST", "/escalation-rules", rule({ id: "w" }), writer), 403, "forbidden");
    const evaluated = await f.request("POST", "/escalations/evaluate", { at: job.updatedAt + 31 * MINUTE_MS });
    const { opened } = await evaluated.json() as { opened: { id: number }[] };
    const listed = await f.request("GET", "/escalations?stage=active", undefined, reader);
    expect((await listed.json() as { total: number }).total).toBe(1);
    const ack = await f.request("POST", `/escalations/${opened[0]!.id}/acknowledge`, undefined, reader);
    expect((await ack.json() as { acknowledgedBy: string }).acknowledgedBy).toBe(reader.id);
    const summary = await f.request("GET", "/escalations/summary", undefined, reader);
    expect(summary.status).toBe(200);
    await expectError(await f.request("GET", `/escalations/${opened[0]!.id}`, undefined, outsider), 403);
    await expectError(await f.request("GET", "/escalations/abc", undefined, reader), 400, "validation_failed");
  });
});
