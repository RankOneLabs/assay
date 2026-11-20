import { describe, expect, test } from "bun:test";
import { values as stages } from "../../stage/types.ts";
import { values as kinds } from "../../evidence_kind/types.ts";
import { fixture, admin, reader, writer, outsider, expectError } from "./helpers.ts";
import { nextRun, type Recurrence } from "../../src/domain/schedules.ts";
import { checksum } from "../../src/domain/checksum.ts";
import { readAccess } from "../../src/domain/access_levels.ts";

const HOUR = 3_600_000;
// Monday 2024-01-01 10:00 UTC.
const monday = Date.UTC(2024, 0, 1, 10);

function daily(hour: number, utcOffsetMinutes = 0): Recurrence {
  return { cadence: "daily", weekday: null, hour, utcOffsetMinutes };
}

function weekly(weekday: number, hour: number, utcOffsetMinutes = 0): Recurrence {
  return { cadence: "weekly", weekday, hour, utcOffsetMinutes };
}

describe("next run arithmetic", () => {
  test("daily runs fall later today or tomorrow, strictly after the instant", () => {
    expect(nextRun(daily(11), monday)).toBe(Date.UTC(2024, 0, 1, 11));
    expect(nextRun(daily(9), monday)).toBe(Date.UTC(2024, 0, 2, 9));
    expect(nextRun(daily(10), monday)).toBe(Date.UTC(2024, 0, 2, 10));
  });

  test("offsets move local midnight in both directions", () => {
    // UTC+2: it is already 12:00 locally, so 09:00 local is tomorrow, 07:00 UTC.
    expect(nextRun(daily(9, 120), monday)).toBe(Date.UTC(2024, 0, 2, 7));
    // UTC-5: it is 05:00 locally, so 23:00 local tonight is 04:00 UTC tomorrow.
    expect(nextRun(daily(23, -300), monday)).toBe(Date.UTC(2024, 0, 2, 4));
  });

  test("weekly runs wrap past the end of the week", () => {
    expect(nextRun(weekly(0, 8), monday)).toBe(Date.UTC(2024, 0, 7, 8));
    expect(nextRun(weekly(1, 12), monday)).toBe(Date.UTC(2024, 0, 1, 12));
    expect(nextRun(weekly(1, 8), monday)).toBe(Date.UTC(2024, 0, 8, 8));
    // Sunday 20:00 UTC is already Monday 06:00 at UTC+10.
    expect(nextRun(weekly(1, 9, 600), Date.UTC(2024, 0, 7, 20))).toBe(Date.UTC(2024, 0, 7, 23));
  });
});

describe("digest schedules", () => {
  test("readers own their schedules and the first run is computed on creation", () => {
    using f = fixture();
    const created = f.context.digests.createSchedule(reader, { id: "mine", cadence: "daily", hour: 9 });
    expect(created).toMatchObject({
      principal: reader.id, weekday: null, utcOffsetMinutes: 0, enabled: true, revision: 1,
      nextRunAt: 9 * HOUR, lastRunAt: null,
    });
    f.context.digests.createSchedule(admin, { id: "theirs", cadence: "weekly", weekday: 2, hour: 7 });
    expect(f.context.digests.listSchedules(reader).map(item => item.id)).toEqual(["mine"]);
    expect(() => f.context.digests.createSchedule(writer, { id: "w", cadence: "daily", hour: 9 }))
      .toThrow("permission required");
  });

  test("cadence and weekday must agree and fields stay in range", () => {
    using f = fixture();
    const create = (input: Record<string, unknown>) =>
      () => f.context.digests.createSchedule(reader, { id: "s", hour: 9, ...input });
    expect(create({ cadence: "weekly" })).toThrow("need a weekday");
    expect(create({ cadence: "daily", weekday: 3 })).toThrow("need a weekday");
    expect(create({ cadence: "hourly" })).toThrow();
    expect(create({ cadence: "daily", hour: 24 })).toThrow();
    expect(create({ cadence: "daily", utcOffsetMinutes: 900 })).toThrow();
  });

  test("updates recompute the next run and refuse stale revisions", () => {
    using f = fixture();
    f.context.digests.createSchedule(reader, { id: "mine", cadence: "daily", hour: 9 });
    expect(() => f.context.digests.updateSchedule(reader, "mine", {
      cadence: "weekly", expectedRevision: 1,
    })).toThrow("need a weekday");
    // The fixture clock starts on Thursday 1970-01-01; the next Wednesday is the 7th.
    const weekly = f.context.digests.updateSchedule(reader, "mine", {
      cadence: "weekly", weekday: 3, expectedRevision: 1,
    });
    expect(weekly).toMatchObject({ weekday: 3, revision: 2, nextRunAt: 6 * 24 * HOUR + 9 * HOUR });
    const back = f.context.digests.updateSchedule(reader, "mine", { cadence: "daily", expectedRevision: 2 });
    expect(back).toMatchObject({ weekday: null, nextRunAt: 9 * HOUR });
    expect(() => f.context.digests.updateSchedule(reader, "mine", { hour: 3, expectedRevision: 2 }))
      .toThrow("revision changed");
    expect(() => f.context.digests.updateSchedule(admin, "mine", { hour: 3, expectedRevision: 3 }))
      .toThrow("not found");
  });

  test("each principal has a bounded number of schedules", () => {
    using f = fixture();
    for (let index = 0; index < 10; index++) {
      f.context.digests.createSchedule(reader, { id: `s${index}`, cadence: "daily", hour: index });
    }
    expect(() => f.context.digests.createSchedule(reader, { id: "extra", cadence: "daily", hour: 1 }))
      .toThrow("limit");
    expect(() => f.context.digests.createSchedule(admin, { id: "s0", cadence: "daily", hour: 1 }))
      .toThrow("already exists");
  });

  test("administrators list enabled schedules that are due", () => {
    using f = fixture();
    f.context.digests.createSchedule(reader, { id: "mine", cadence: "daily", hour: 9 });
    f.context.digests.createSchedule(admin, { id: "off", cadence: "daily", hour: 1, enabled: false });
    expect(f.context.digests.due(admin, { at: String(9 * HOUR - 1) })).toEqual([]);
    expect(f.context.digests.due(admin, { at: String(9 * HOUR) }).map(item => item.id)).toEqual(["mine"]);
    expect(f.context.digests.due(outsider, { at: String(9 * HOUR) })).toEqual([]);
    expect(() => f.context.digests.due(reader, {})).toThrow("permission required");
  });
});

describe("digest generation", () => {
  const at = 10_000_000;

  function seeded() {
    const f = fixture();
    f.context.digests.createSchedule(reader, { id: "mine", cadence: "daily", hour: 9 });
    f.create("moved");
    f.create("evidenced");
    f.context.jobs.transition(admin, "moved", { stage: "active", expectedRevision: 1, reason: "start" });
    f.attach("photo", "evidenced", { kind: "image" });
    f.attach("statement", "evidenced", { kind: "testimony" });
    return f;
  }

  test("counts the period since the last run by stage and kind and advances the schedule", () => {
    using f = seeded();
    const { digest, schedule } = f.context.digests.generate(reader, "mine", { at });
    expect(digest.content.jobs).toEqual({ created: 2, changed: 2 });
    expect(digest.content.transitions.map(item => item.stage)).toEqual([...stages]);
    expect(digest.content.evidence.map(item => item.kind)).toEqual([...kinds]);
    for (const item of digest.content.transitions) expect(item.count).toBe(item.stage === "active" ? 1 : 0);
    for (const item of digest.content.evidence) {
      expect(item.count).toBe(item.kind === "image" || item.kind === "testimony" ? 1 : 0);
    }
    expect(digest).toMatchObject({ principal: reader.id, periodEnd: at, generatedBy: reader.id });
    expect(digest.checksum).toBe(checksum(JSON.stringify(digest.content)));
    expect(schedule).toMatchObject({ lastRunAt: at, nextRunAt: 9 * HOUR, revision: 2 });
    expect(() => f.context.digests.generate(reader, "mine", { at })).toThrow("period is empty");
    const next = f.context.digests.generate(reader, "mine", { at: at + HOUR }).digest;
    expect(next).toMatchObject({ periodStart: at, periodEnd: at + HOUR });
    expect(next.content.jobs).toEqual({ created: 0, changed: 0 });
  });

  test("administrators generate for members; others are refused", () => {
    using f = seeded();
    expect(() => f.context.digests.generate(writer, "mine", { at })).toThrow("permission required");
    expect(() => f.context.digests.generate(outsider, "mine", { at })).toThrow("not found");
    f.context.digests.createSchedule(admin, { id: "theirs", cadence: "daily", hour: 9 });
    expect(() => f.context.digests.generate(reader, "theirs", { at })).toThrow("permission required");
    const { digest } = f.context.digests.generate(admin, "mine", { at });
    expect(digest).toMatchObject({ principal: reader.id, generatedBy: admin.id });
    expect(f.context.digests.listDigests(reader, {}).total).toBe(1);
    expect(f.context.digests.listDigests(admin, {}).total).toBe(0);
  });

  test("disabled schedules and owners without read access produce nothing", () => {
    using f = seeded();
    f.context.digests.updateSchedule(reader, "mine", { enabled: false, expectedRevision: 1 });
    expect(() => f.context.digests.generate(reader, "mine", { at })).toThrow("disabled");
    f.context.digests.updateSchedule(reader, "mine", { enabled: true, expectedRevision: 2 });
    f.context.grantRepository.revoke(reader, readAccess);
    expect(() => f.context.digests.generate(admin, "mine", { at })).toThrow("can no longer read");
    expect(f.context.digests.listDigests(admin, {}).total).toBe(0);
  });

  test("stored digests page newest first and verify their checksum", () => {
    using f = seeded();
    const first = f.context.digests.generate(reader, "mine", { at }).digest;
    const second = f.context.digests.generate(reader, "mine", { at: at + HOUR }).digest;
    const page = f.context.digests.listDigests(reader, { limit: "1" });
    expect(page).toMatchObject({ total: 2, nextOffset: 1 });
    expect(page.items[0]!.id).toBe(second.id);
    expect(f.context.digests.getDigest(reader, first.id)).toMatchObject({ verified: true, content: first.content });
    f.context.db.query("UPDATE digests SET content = '{}' WHERE id = ?").run(first.id);
    expect(f.context.digests.getDigest(reader, first.id).verified).toBe(false);
    expect(() => f.context.digests.getDigest(admin, first.id)).toThrow("not found");
    expect(() => f.context.digests.getDigest(reader, "zero")).toThrow();
  });
});

describe("digest routes", () => {
  test("schedules, generation and retrieval work over HTTP", async () => {
    using f = fixture();
    const created = await f.request("POST", "/digests/schedules", { id: "mine", cadence: "daily", hour: 9 }, reader);
    expect(created.status).toBe(201);
    const listed = await f.request("GET", "/digests/schedules", undefined, reader);
    expect((await listed.json() as { id: string }[]).map(item => item.id)).toEqual(["mine"]);
    await expectError(await f.request("GET", "/digests/schedules/due", undefined, reader), 403, "forbidden");
    const due = await f.request("GET", `/digests/schedules/due?at=${9 * HOUR}`);
    expect((await due.json() as unknown[]).length).toBe(1);
    const generated = await f.request("POST", "/digests/schedules/mine/generate", { at: 10_000_000 }, reader);
    expect(generated.status).toBe(201);
    const { digest } = await generated.json() as { digest: { id: number } };
    const page = await f.request("GET", "/digests", undefined, reader);
    expect((await page.json() as { total: number }).total).toBe(1);
    const fetched = await f.request("GET", `/digests/${digest.id}`, undefined, reader);
    expect((await fetched.json() as { verified: boolean }).verified).toBe(true);
    await expectError(await f.request("GET", `/digests/${digest.id}`, undefined, admin), 404, "not_found");
    await expectError(await f.request("PATCH", "/digests/schedules/mine", { hour: 30, expectedRevision: 2 }, reader), 400);
  });
});
