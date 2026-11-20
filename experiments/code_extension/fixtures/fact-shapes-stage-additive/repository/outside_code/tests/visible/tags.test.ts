import { describe, expect, test } from "bun:test";
import { fixture, admin, reader, writer, outsider, expectError } from "./helpers.ts";
import { formatQuery, parseQuery } from "../../src/domain/search_query.ts";
import { ServiceError } from "../../src/domain/errors.ts";
import { maxSavedSearches } from "../../src/services/searches.ts";

function queryError(source: string): ServiceError {
  try {
    parseQuery(source);
  } catch (error) {
    if (error instanceof ServiceError) return error;
    throw error;
  }
  throw new Error(`query parsed: ${source}`);
}

describe("job tags", () => {
  test("tags are normalized, deduplicated and recorded once in history", () => {
    using f = fixture();
    f.create();
    const result = f.context.tags.add(writer, "job", { tags: ["Needs Review", "needs_review", "billing"] });
    expect(result.added).toEqual(["needs-review", "billing"]);
    expect(result.tags.map(item => item.tag)).toEqual(["billing", "needs-review"]);
    expect(result.tags[0]!.addedBy).toBe("writer");
    expect(f.context.tags.add(admin, "job", { tags: ["BILLING"] }).added).toEqual([]);
    const tagged = f.context.jobs.history(admin, "job").filter(event => event.action === "job.tagged");
    expect(tagged.map(event => JSON.parse(event.detail))).toEqual([{ tags: ["needs-review", "billing"] }]);
    expect(f.context.tags.list(reader, "job").map(item => item.tag)).toEqual(["billing", "needs-review"]);
  });

  test("malformed tags and the per-job limit refuse the whole request", () => {
    using f = fixture();
    f.create();
    for (const tag of ["", "   ", "a/b", "-lead", "x".repeat(41)]) {
      expect(() => f.context.tags.add(admin, "job", { tags: ["kept", tag] })).toThrow();
    }
    expect(() => f.context.tags.add(admin, "job", { tags: [] })).toThrow();
    f.context.tags.add(admin, "job", { tags: Array.from({ length: 19 }, (_, index) => `t${index}`) });
    expect(() => f.context.tags.add(admin, "job", { tags: ["one", "two"] })).toThrow("at most 20 tags");
    expect(f.context.tags.list(admin, "job")).toHaveLength(19);
    f.context.tags.add(admin, "job", { tags: ["t0", "last"] });
    expect(f.context.tags.list(admin, "job")).toHaveLength(20);
  });

  test("removing a tag records an event and unknown tags are missing", () => {
    using f = fixture();
    f.create();
    f.context.tags.add(admin, "job", { tags: ["billing", "urgent"] });
    expect(f.context.tags.remove(writer, "job", "Billing").map(item => item.tag)).toEqual(["urgent"]);
    expect(f.context.jobs.history(admin, "job").at(-1)).toMatchObject({ action: "job.untagged", actor: "writer" });
    expect(() => f.context.tags.remove(admin, "job", "billing")).toThrow("not found");
  });

  test("archived jobs are read only and tag access follows job permissions", () => {
    using f = fixture();
    f.create();
    f.context.tags.add(admin, "job", { tags: ["billing"] });
    expect(() => f.context.tags.add(reader, "job", { tags: ["x"] })).toThrow("permission required");
    expect(() => f.context.tags.list(writer, "job")).toThrow("permission required");
    expect(() => f.context.tags.add(outsider, "job", { tags: ["x"] })).toThrow("another project");
    expect(() => f.context.tags.list(outsider, "job")).toThrow("another project");
    f.context.jobs.archive(admin, "job", { expectedRevision: 1 });
    expect(() => f.context.tags.add(admin, "job", { tags: ["x"] })).toThrow("read only");
    expect(() => f.context.tags.remove(admin, "job", "billing")).toThrow("read only");
    expect(f.context.tags.list(reader, "job").map(item => item.tag)).toEqual(["billing"]);
  });

  test("project tag counts order by use, count archived jobs and stay in the project", () => {
    using f = fixture();
    f.create("first");
    f.create("second");
    f.create("third");
    f.context.tags.add(admin, "first", { tags: ["billing", "urgent"] });
    f.context.tags.add(admin, "second", { tags: ["billing"] });
    f.context.tags.add(admin, "third", { tags: ["billing", "audit"] });
    f.context.jobs.archive(admin, "third", { expectedRevision: 1 });
    const page = f.context.tags.project(reader, 2, 0);
    expect(page.items).toEqual([
      { tag: "billing", jobs: 3, archived: 1 },
      { tag: "audit", jobs: 1, archived: 1 },
    ]);
    expect(page.total).toBe(3);
    expect(page.nextOffset).toBe(2);
    expect(f.context.tags.project(reader, 2, 2).items.map(item => item.tag)).toEqual(["urgent"]);
    expect(f.context.tags.project(outsider, 10, 0).items).toEqual([]);
    expect(() => f.context.tags.project(writer, 10, 0)).toThrow("permission required");
  });

  test("rename changes every job in the project, archived ones included", () => {
    using f = fixture();
    f.create("first");
    f.create("second");
    f.context.tags.add(admin, "first", { tags: ["bug"] });
    f.context.tags.add(admin, "second", { tags: ["bug", "urgent"] });
    f.context.jobs.archive(admin, "second", { expectedRevision: 1 });
    f.context.jobs.create(outsider, { id: "foreign", title: "Foreign", owner: "owner", project: "other" });
    f.context.tags.add(outsider, "foreign", { tags: ["bug"] });
    expect(f.context.tags.rename(admin, { from: "bug", to: "Defect" })).toEqual({ target: "defect", jobs: ["first", "second"] });
    expect(f.context.tags.list(admin, "second").map(item => item.tag)).toEqual(["defect", "urgent"]);
    expect(f.context.tags.list(outsider, "foreign").map(item => item.tag)).toEqual(["bug"]);
    const event = f.context.jobs.history(admin, "first").at(-1)!;
    expect(event.action).toBe("job.tag_renamed");
    expect(JSON.parse(event.detail)).toEqual({ sources: ["bug"], target: "defect" });
    expect(() => f.context.tags.rename(admin, { from: "bug", to: "other" })).toThrow("not found");
    expect(() => f.context.tags.rename(admin, { from: "defect", to: "urgent" })).toThrow("merge");
    expect(() => f.context.tags.rename(admin, { from: "defect", to: "DEFECT" })).toThrow();
    expect(() => f.context.tags.rename(writer, { from: "defect", to: "fault" })).toThrow("permission required");
  });

  test("merge folds sources into the target without duplicating it", () => {
    using f = fixture();
    f.create("first");
    f.create("second");
    f.context.tags.add(admin, "first", { tags: ["bug", "defect", "fault"] });
    f.context.tags.add(admin, "second", { tags: ["fault"] });
    const merged = f.context.tags.merge(admin, { sources: ["bug", "fault"], target: "defect" });
    expect(merged.jobs).toEqual(["first", "second"]);
    expect(f.context.tags.list(admin, "first").map(item => item.tag)).toEqual(["defect"]);
    expect(f.context.tags.list(admin, "second").map(item => item.tag)).toEqual(["defect"]);
    expect(f.context.jobs.history(admin, "second").at(-1)!.action).toBe("job.tags_merged");
    expect(() => f.context.tags.merge(admin, { sources: ["defect"], target: "defect" })).toThrow();
    expect(() => f.context.tags.merge(admin, { sources: ["a", "a"], target: "b" })).toThrow();
    expect(() => f.context.tags.merge(admin, { sources: ["gone"], target: "defect" })).toThrow("not found");
  });

  test("tags are deleted with their job", () => {
    using f = fixture();
    f.create();
    f.context.tags.add(admin, "job", { tags: ["billing"] });
    const archived = f.context.jobs.archive(admin, "job", { expectedRevision: 1 });
    f.context.maintenance.purge(admin, archived.archivedAt! + 1, 10);
    expect(f.context.tags.project(admin, 10, 0).total).toBe(0);
  });
});

describe("search queries", () => {
  test("terms parse into a canonical form", () => {
    const query = parseQuery("  Tag:Billing owner:sam stage:active priority>=3 priority<=7 invoice  due tag:billing ");
    expect(query).toEqual({
      tags: ["billing"], owner: "sam", stage: "active", minPriority: 3, maxPriority: 7,
      archived: false, text: "invoice due",
    });
    expect(formatQuery(query)).toBe("tag:billing owner:sam stage:active priority>=3 priority<=7 invoice due");
    expect(formatQuery(parseQuery("priority=4 archived:true"))).toBe("priority:4 archived:true");
    expect(parseQuery("")).toEqual({ tags: [], archived: false });
  });

  test("malformed queries name the problem and its position", () => {
    expect(queryError("color:red").message).toContain("unknown field \"color\"");
    expect(queryError("tag:ok stage:unsupported_future").detail).toEqual({ position: 7 });
    expect(queryError("owner:a owner:b").message).toContain("only once");
    expect(queryError("priority>=8 priority<=3").message).toContain("range is empty");
    expect(queryError("priority>=high").message).toContain("whole number");
    expect(queryError("priority:101").message).toContain("at most 100");
    expect(queryError("stage>=active").message).toContain("use \":\"");
    expect(queryError("owner:").message).toContain("needs a value");
    expect(queryError("10:30").message).toContain("malformed term");
    expect(queryError("archived:maybe").code).toBe("invalid_query");
    expect(queryError("x".repeat(501)).message).toContain("longer than 500");
  });
});

describe("saved searches", () => {
  test("running a search filters by tags, fields and text in the project", () => {
    using f = fixture();
    f.create("match", { owner: "sam", priority: 5, title: "Invoice run" });
    f.create("untagged", { owner: "sam", priority: 5, title: "Invoice run" });
    f.create("low", { owner: "sam", priority: 1, title: "Invoice run" });
    f.create("busy", { owner: "sam", priority: 9, title: "Invoice run" });
    f.context.jobs.transition(admin, "busy", { stage: "active", expectedRevision: 1, reason: "start" });
    for (const id of ["match", "low", "busy"]) f.context.tags.add(admin, id, { tags: ["billing", "q3"] });
    const search = f.context.searches.create(reader, {
      id: "mine", name: "Billing", query: "TAG:billing tag:q3 owner:sam priority>=2 invoice",
    });
    expect(search).toMatchObject({ query: "tag:billing tag:q3 owner:sam priority>=2 invoice", shared: false, revision: 1 });
    expect(f.context.searches.run(reader, "mine", 25, 0).items.map(job => job.id)).toEqual(["busy", "match"]);
    const stage = f.context.jobRepository.require("match").stage;
    f.context.searches.update(reader, "mine", { query: `tag:billing stage:${stage}`, expectedRevision: 1 });
    const page = f.context.searches.run(reader, "mine", 1, 0);
    expect(page.items.map(job => job.id)).toEqual(["match"]);
    expect(page).toMatchObject({ total: 2, nextOffset: 1 });
    f.context.jobs.archive(admin, "low", { expectedRevision: 1 });
    expect(f.context.searches.run(reader, "mine", 25, 0).items.map(job => job.id)).toEqual(["match"]);
  });

  test("private searches stay private and sharing needs write permission", () => {
    using f = fixture();
    f.context.searches.create(admin, { id: "private", name: "Mine", query: "" });
    f.context.searches.create(admin, { id: "shared", name: "Team", query: "tag:x", shared: true });
    expect(() => f.context.searches.create(reader, { id: "r", name: "R", query: "", shared: true }))
      .toThrow("permission required");
    expect(() => f.context.searches.get(reader, "private")).toThrow("not found");
    expect(() => f.context.searches.get(outsider, "shared")).toThrow("not found");
    expect(f.context.searches.list(reader, 50, 0).items.map(search => search.id)).toEqual(["shared"]);
    expect(f.context.searches.list(admin, 50, 0).items.map(search => search.id)).toEqual(["private", "shared"]);
    expect(() => f.context.searches.update(reader, "shared", { name: "Taken", expectedRevision: 1 }))
      .toThrow("only the owner");
    expect(() => f.context.searches.remove(reader, "shared", { expectedRevision: 1 })).toThrow("permission required");
    f.context.searches.create(reader, { id: "reader", name: "R", query: "" });
    expect(() => f.context.searches.update(reader, "reader", { shared: true, expectedRevision: 1 }))
      .toThrow("permission required");
    expect(() => f.context.searches.create(writer, { id: "w", name: "W", query: "" })).toThrow("permission required");
  });

  test("updates and deletes check revisions, and owners keep a bounded number", () => {
    using f = fixture();
    f.context.searches.create(reader, { id: "s", name: "First", query: "tag:a" });
    expect(f.context.searches.update(reader, "s", { name: " Second ", expectedRevision: 1 }))
      .toMatchObject({ name: "Second", query: "tag:a", revision: 2 });
    expect(() => f.context.searches.update(reader, "s", { name: "Third", expectedRevision: 1 })).toThrow("revision changed");
    expect(() => f.context.searches.update(reader, "s", { expectedRevision: 2 })).toThrow();
    expect(() => f.context.searches.update(reader, "s", { query: "bogus:1", expectedRevision: 2 })).toThrow("unknown field");
    expect(() => f.context.searches.create(reader, { id: "s", name: "Again", query: "" })).toThrow("already exists");
    expect(() => f.context.searches.remove(reader, "s", { expectedRevision: 1 })).toThrow("revision changed");
    expect(f.context.searches.remove(reader, "s", { expectedRevision: 2 }).id).toBe("s");
    for (let index = 0; index < maxSavedSearches; index++) {
      f.context.searches.create(reader, { id: `s${index}`, name: `S${index}`, query: "" });
    }
    expect(() => f.context.searches.create(reader, { id: "over", name: "Over", query: "" })).toThrow("at most 50");
    f.context.searches.create(admin, { id: "team", name: "Team", query: "", shared: true });
    expect(f.context.searches.remove(admin, "team", { expectedRevision: 1 }).id).toBe("team");
  });

  test("tag and search routes work over HTTP", async () => {
    using f = fixture();
    f.create("job", { priority: 4 });
    const added = await f.request("POST", "/jobs/job/tags", { tags: ["Ops"] }, writer);
    expect(added.status).toBe(200);
    expect(await added.json()).toMatchObject({ added: ["ops"] });
    expect(await (await f.request("GET", "/tags", undefined, reader)).json())
      .toMatchObject({ items: [{ tag: "ops", jobs: 1, archived: 0 }], total: 1 });
    await expectError(await f.request("POST", "/searches", { id: "bad", name: "Bad", query: "tag:" }, reader), 400, "invalid_query");
    const created = await f.request("POST", "/searches", { id: "ops", name: "Ops", query: "tag:ops" }, reader);
    expect(created.status).toBe(201);
    expect(created.headers.get("location")).toBe("/searches/ops");
    expect((await f.request("GET", "/searches/ops", undefined, reader)).headers.get("etag")).toBe("\"1\"");
    const run = await (await f.request("GET", "/searches/ops/run?limit=5", undefined, reader)).json() as {
      items: { id: string }[];
    };
    expect(run.items.map(job => job.id)).toEqual(["job"]);
    expect((await f.request("PATCH", "/searches/ops", { shared: true, expectedRevision: 1 }, reader)).status).toBe(403);
    expect((await f.request("POST", "/tags/rename", { from: "ops", to: "infra" })).status).toBe(200);
    expect(await (await f.request("DELETE", "/jobs/job/tags/infra", undefined, writer)).json()).toEqual([]);
    await expectError(await f.request("POST", "/tags/merge", { sources: ["ops"], target: "infra" }), 404, "not_found");
    expect((await f.request("GET", "/searches", undefined, outsider)).status).toBe(200);
    expect((await f.request("DELETE", "/searches/ops", { expectedRevision: 1 }, reader)).status).toBe(200);
    await expectError(await f.request("GET", "/jobs/job/tags", undefined, outsider), 403, "forbidden");
  });
});
