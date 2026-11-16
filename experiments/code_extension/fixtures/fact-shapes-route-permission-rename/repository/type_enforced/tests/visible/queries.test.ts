import { describe, expect, test } from "bun:test";
import { fixture, admin, outsider } from "./helpers.ts";

describe("job query semantics", () => {
  test("priority ordering has a stable id tiebreaker for identical timestamps", () => {
    using f = fixture();
    f.create("low", { priority: 1 });
    f.create("high", { priority: 99 });
    f.create("middle", { priority: 20 });
    const page = f.context.jobs.list(admin, {});
    expect(page.items.map(job => job.id)).toEqual(["high", "middle", "low"]);
    expect(page.total).toBe(3);
    expect(page.offset).toBe(0);
    expect(page.limit).toBe(25);
    expect(page.nextOffset).toBeNull();
  });

  test("pagination visits each row exactly once", () => {
    using f = fixture();
    for (let index = 0; index < 7; index++) f.create(`job-${index}`);
    const ids: string[] = [];
    let offset: number | null = 0;
    while (offset !== null) {
      const page = f.context.jobs.list(admin, { limit: "2", offset: String(offset) });
      expect(page.items.length).toBeLessThanOrEqual(2);
      expect(page.total).toBe(7);
      ids.push(...page.items.map(job => job.id));
      offset = page.nextOffset;
    }
    expect(ids).toHaveLength(7);
    expect(new Set(ids).size).toBe(7);
  });

  test("offset beyond the end returns an empty terminal page", () => {
    using f = fixture();
    f.create();
    const page = f.context.jobs.list(admin, { offset: "10", limit: "2" });
    expect(page.items).toEqual([]);
    expect(page.total).toBe(1);
    expect(page.nextOffset).toBeNull();
  });

  test("filters combine stage, owner and minimum priority", () => {
    using f = fixture();
    f.create("match", { owner: "sam", priority: 8 });
    f.create("wrong-owner", { owner: "pat", priority: 8 });
    f.create("low-priority", { owner: "sam", priority: 2 });
    f.create("wrong-stage", { owner: "sam", priority: 9 });
    f.context.jobs.transition(admin, "wrong-stage", {
      stage: "active", expectedRevision: 1, reason: "start",
    });
    const page = f.context.jobs.list(admin, { owner: "sam", stage: "queued", minPriority: "5" });
    expect(page.items.map(job => job.id)).toEqual(["match"]);
    expect(page.total).toBe(1);
  });

  test("search matches both title and description", () => {
    using f = fixture();
    f.create("title", { title: "Important invoice" });
    f.create("description", { description: "An invoice is attached" });
    f.create("irrelevant", { title: "Unrelated", description: "Nothing here" });
    const page = f.context.jobs.list(admin, { query: "invoice" });
    expect(page.items.map(job => job.id)).toEqual(["title", "description"]);
    expect(page.total).toBe(2);
  });

  test("search treats SQL wildcard characters literally", () => {
    using f = fixture();
    f.create("percent", { title: "100% ready" });
    f.create("underscore", { title: "job_name" });
    f.create("slash", { title: "path\\name" });
    f.create("other", { title: "1000 ready" });
    expect(f.context.jobs.list(admin, { query: "%" }).items.map(job => job.id)).toEqual(["percent"]);
    expect(f.context.jobs.list(admin, { query: "_" }).items.map(job => job.id)).toEqual(["underscore"]);
    expect(f.context.jobs.list(admin, { query: "\\" }).items.map(job => job.id)).toEqual(["slash"]);
  });

  test("search input is bound rather than interpolated into SQL", () => {
    using f = fixture();
    f.create("literal", { title: "' OR 1=1 --" });
    f.create("safe");
    const page = f.context.jobs.list(admin, { query: "' OR 1=1 --" });
    expect(page.items.map(job => job.id)).toEqual(["literal"]);
    expect(f.context.jobRepository.count()).toBe(2);
  });

  test("archive filter distinguishes active and archived records", () => {
    using f = fixture();
    f.create("visible");
    f.create("archived");
    f.context.jobs.archive(admin, "archived", { expectedRevision: 1 });
    expect(f.context.jobs.list(admin, {}).total).toBe(2);
    expect(f.context.jobs.list(admin, { archived: "false" }).items.map(job => job.id)).toEqual(["visible"]);
    expect(f.context.jobs.list(admin, { archived: "true" }).items.map(job => job.id)).toEqual(["archived"]);
  });

  test("project scoping applies before count and pagination", () => {
    using f = fixture();
    f.create("local");
    f.context.jobs.create(outsider, {
      id: "foreign", title: "Foreign", owner: "owner", project: "other",
    });
    const local = f.context.jobs.list(admin, { limit: "1" });
    const foreign = f.context.jobs.list(outsider, { limit: "1" });
    expect(local.total).toBe(1);
    expect(foreign.total).toBe(1);
    expect(local.items[0]?.id).toBe("local");
    expect(foreign.items[0]?.id).toBe("foreign");
    expect(() => f.context.jobs.list(admin, { project: "other" })).toThrow("permission");
  });

  test("invalid pagination is rejected before it reaches the repository", () => {
    using f = fixture();
    f.create();
    expect(() => f.context.jobs.list(admin, { limit: "0" })).toThrow();
    expect(() => f.context.jobs.list(admin, { limit: "101" })).toThrow();
    expect(() => f.context.jobs.list(admin, { offset: "-1" })).toThrow();
    expect(() => f.context.jobs.list(admin, { limit: "1.5" })).toThrow();
    expect(() => f.context.jobs.list(admin, { stage: "triaged" })).toThrow();
    expect(() => f.context.jobs.list(admin, { archived: "maybe" })).toThrow();
  });
});

describe("event pagination and search stability", () => {
  test("event cursors use sequence rather than timestamps shared by multiple events", () => {
    using f = fixture();
    f.create();
    const repository = f.context.eventRepository;
    for (let index = 0; index < 6; index++) {
      repository.append("job", "manual.event", "operator", { index }, 2000);
    }
    const seen: number[] = [];
    let cursor = 0;
    while (true) {
      const page = f.context.jobs.history(admin, "job", cursor, 2);
      if (!page.length) break;
      seen.push(...page.map(event => event.sequence));
      cursor = page.at(-1)!.sequence;
    }
    expect(seen).toHaveLength(7);
    expect(new Set(seen).size).toBe(7);
    expect(seen).toEqual([...seen].sort((a, b) => a - b));
  });

  test("event pages for one job do not include another job's interleaved events", () => {
    using f = fixture();
    f.create("first");
    f.create("second");
    f.context.jobs.patch(admin, "first", { title: "First update", expectedRevision: 1 });
    f.context.jobs.patch(admin, "second", { title: "Second update", expectedRevision: 1 });
    const first = f.context.jobs.history(admin, "first");
    const second = f.context.jobs.history(admin, "second");
    expect(first).toHaveLength(2);
    expect(second).toHaveLength(2);
    expect(first.every(event => event.jobId === "first")).toBe(true);
    expect(second.every(event => event.jobId === "second")).toBe(true);
    expect(first.every(event => !second.some(other => other.sequence === event.sequence))).toBe(true);
  });

  test("an empty search term behaves like an omitted term without exposing other projects", () => {
    using f = fixture();
    f.create();
    const all = f.context.jobs.list(admin, {});
    const blank = f.context.jobs.list(admin, { query: "   " });
    expect(blank).toEqual(all);
    expect(f.context.jobs.list(outsider, { query: "   " }).items).toEqual([]);
  });

  test("search state is read fresh after a title patch and after archive restoration", () => {
    using f = fixture();
    f.create("job", { title: "Before" });
    expect(f.context.jobs.list(admin, { query: "After" }).total).toBe(0);
    f.context.jobs.patch(admin, "job", { title: "After", expectedRevision: 1 });
    expect(f.context.jobs.list(admin, { query: "Before" }).total).toBe(0);
    expect(f.context.jobs.list(admin, { query: "After" }).total).toBe(1);
    f.context.jobs.archive(admin, "job", { expectedRevision: 2 });
    expect(f.context.jobs.list(admin, { query: "After", archived: "false" }).total).toBe(0);
    f.context.jobs.restore(admin, "job", { expectedRevision: 3 });
    expect(f.context.jobs.list(admin, { query: "After", archived: "false" }).total).toBe(1);
  });
});
