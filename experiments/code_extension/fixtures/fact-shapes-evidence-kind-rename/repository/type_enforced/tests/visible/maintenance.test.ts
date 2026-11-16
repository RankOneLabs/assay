import { vocabularyStore as canonicalStore } from "../../src/vocabulary.ts";
function canonical(feature: string): never { return canonicalStore.values(feature)[0] as never; }
import { DependencyRepository } from "../../src/repositories/dependencies.ts";
import { describe, expect, test } from "bun:test";
import { fixture, seedArchives, admin, reader, writer, outsider, expectError } from "./helpers.ts";

describe("maintenance operations", () => {
  test("bulk archive creates one event and revision for each job", () => {
    using f = fixture();
    f.create("first");
    f.create("second");
    const archived = f.context.maintenance.archive(admin, {
      ids: ["first", "second"], reason: "retention review",
    });
    expect(archived).toEqual(["first", "second"]);
    for (const id of archived) {
      expect(f.context.jobRepository.require(id).archivedAt).not.toBeNull();
      expect(f.context.jobRepository.require(id).revision).toBe(2);
      const event = f.context.jobs.history(admin, id).at(-1)!;
      expect(event.action).toBe("job.archived");
      expect(JSON.parse(event.detail)).toEqual({ reason: "retention review" });
    }
    expect(f.context.jobRepository.count()).toBe(0);
  });

  test("duplicate bulk ids are refused before an archive can occur", () => {
    using f = fixture();
    f.create();
    expect(() => f.context.maintenance.archive(admin, {
      ids: ["job", "job"], reason: "duplicate",
    })).toThrow();
    expect(f.context.jobRepository.require("job").archivedAt).toBeNull();
    expect(f.context.eventRepository.count("job")).toBe(1);
  });

  test("configured bulk limit refuses a whole batch", () => {
    using f = fixture({ maxBulkJobs: 1 });
    f.create("first");
    f.create("second");
    expect(() => f.context.maintenance.archive(admin, {
      ids: ["first", "second"], reason: "too many",
    })).toThrow("bulk job limit");
    expect(f.context.jobRepository.count()).toBe(2);
    expect(f.context.jobRepository.require("first").revision).toBe(1);
  });

  test("an unknown late id does not leave earlier jobs archived", () => {
    using f = fixture();
    f.create();
    expect(() => f.context.maintenance.archive(admin, {
      ids: ["job", "missing"], reason: "rollback",
    })).toThrow("not found");
    expect(f.context.jobRepository.require("job").archivedAt).toBeNull();
    expect(f.context.eventRepository.count("job")).toBe(1);
  });

  test("purge deletes archived records and cascades their evidence and events", () => {
    using f = fixture();
    f.create();
    f.attach();
    const archived = f.context.jobs.archive(admin, "job", { expectedRevision: 1 });
    const purged = f.context.maintenance.purge(admin, archived.archivedAt! + 1, 10);
    expect(purged).toEqual(["job"]);
    expect(f.context.jobRepository.get("job")).toBeNull();
    expect(f.context.evidenceRepository.get("evidence")).toBeNull();
    expect(f.context.eventRepository.count("job")).toBe(0);
  });

  test("purge leaves unarchived records and honors a strict cutoff", () => {
    using f = fixture();
    f.create("live");
    f.create("old");
    const archived = f.context.jobs.archive(admin, "old", { expectedRevision: 1 });
    expect(f.context.maintenance.purge(admin, archived.archivedAt!, 10)).toEqual([]);
    expect(f.context.jobRepository.get("old")).not.toBeNull();
    const removed = f.context.maintenance.purge(admin, archived.archivedAt! + 1, 10);
    expect(removed).toEqual(["old"]);
    expect(f.context.jobRepository.get("live")).not.toBeNull();
  });

  test("purge limits are stable and repeated batches finish the backlog", () => {
    using f = fixture();
    f.create("first");
    f.create("second");
    f.create("third");
    for (const id of ["first", "second", "third"]) {
      f.context.jobs.archive(admin, id, { expectedRevision: 1 });
    }
    const cutoff = 1006;
    const first = f.context.maintenance.purge(admin, cutoff, 1);
    const second = f.context.maintenance.purge(admin, cutoff, 1);
    const third = f.context.maintenance.purge(admin, cutoff, 1);
    expect(first).toEqual(["first"]);
    expect(second).toEqual(["second"]);
    expect(third).toEqual(["third"]);
    expect(f.context.maintenance.purge(admin, cutoff, 1)).toEqual([]);
  });

  test("purge project isolation is enforced before deleting rows", () => {
    using f = fixture();
    f.create();
    f.context.jobs.archive(admin, "job", { expectedRevision: 1 });
    expect(f.context.maintenance.purge(outsider, 1002, 10)).toEqual([]);
    expect(f.context.jobRepository.get("job")).not.toBeNull();
    expect(f.context.eventRepository.count("job")).toBe(2);
  });

  test("purge rejects future, negative and nonintegral cutoffs", () => {
    using f = fixture();
    expect(() => f.context.maintenance.purge(admin, -1, 1)).toThrow("cutoff");
    expect(() => f.context.maintenance.purge(admin, 100000, 1)).toThrow("cutoff");
    expect(() => f.context.maintenance.purge(admin, 1.5, 1)).toThrow("cutoff");
    expect(() => f.context.maintenance.purge(admin, 0, 0)).toThrow("batch size");
    expect(() => f.context.maintenance.purge(admin, 0, 101)).toThrow("batch size");
  });

  test("integrity reports are project scoped and do not mutate evidence", () => {
    using f = fixture();
    f.create();
    const original = f.attach();
    expect(f.context.maintenance.integrity(admin)).toEqual({ checked: 1, issues: [] });
    expect(f.context.maintenance.integrity(outsider)).toEqual({ checked: 0, issues: [] });
    expect(f.context.evidenceRepository.require(original.id)).toEqual(original);
    expect(f.context.eventRepository.count("job")).toBe(2);
  });

  test("readers and writers cannot run maintenance", () => {
    using f = fixture();
    f.create();
    expect(() => f.context.maintenance.archive(reader, { ids: ["job"], reason: "no" })).toThrow("permission");
    expect(() => f.context.maintenance.purge(writer, 0, 1)).toThrow("permission");
    expect(() => f.context.maintenance.integrity(reader)).toThrow("permission");
  });

  test("HTTP maintenance exposes authorization and batch results", async () => {
    using f = fixture();
    f.create();
    await expectError(await f.request("POST", "/maintenance/archive", {
      ids: ["job"], reason: "no",
    }, reader), 403);
    const archived = await f.request("POST", "/maintenance/archive", {
      ids: ["job"], reason: "reviewed",
    });
    expect(archived.status).toBe(200);
    expect(await archived.json()).toEqual({ archived: ["job"] });
    const result = await f.request("GET", "/maintenance/integrity");
    expect(await result.json()).toEqual({ checked: 1, issues: [] });
  });
});

describe("evidence integrity diagnostics", () => {
  test("the integrity report names corrupt evidence without rewriting it", () => {
    using f = fixture();
    f.create();
    f.attach();
    f.context.db.query("UPDATE evidence SET content = ? WHERE id = ?").run("corrupt", "evidence");
    const result = f.context.maintenance.integrity(admin);
    expect(result).toEqual({
      checked: 1,
      issues: [{ jobId: "job", evidenceId: "evidence", message: "evidence checksum mismatch" }],
    });
    expect(f.context.evidenceRepository.require("evidence").content).toBe("corrupt");
    expect(f.context.eventRepository.count("job")).toBe(2);
  });

  test("an empty body is reported independently from its invalid digest", () => {
    using f = fixture();
    f.create();
    f.attach();
    f.context.db.query("UPDATE evidence SET content = '' WHERE id = ?").run("evidence");
    const result = f.context.maintenance.integrity(admin);
    expect(result.issues).toHaveLength(2);
    expect(result.issues.some(issue => issue.message === "empty evidence")).toBe(true);
    expect(result.issues.some(issue => issue.message === "evidence checksum mismatch")).toBe(true);
    expect(f.context.maintenance.integrity(outsider)).toEqual({ checked: 0, issues: [] });
  });
});

describe("dependency-aware retention", () => {
  test("retention preserves an archived prerequisite of a retained job", () => {
    using f = fixture();
    f.create("prerequisite");
    f.create("retained");
    f.context.planning.add(admin, "retained", "prerequisite");
    const archived = f.context.jobs.archive(admin, "prerequisite", { expectedRevision: 1 });
    const removed = f.context.maintenance.purge(admin, archived.archivedAt! + 1, 10);
    expect(removed).toEqual([]);
    expect(f.context.jobRepository.get("prerequisite")).not.toBeNull();
    expect(f.context.planning.blockers(reader, "retained").map(job => job.id)).toEqual(["prerequisite"]);
    expect(f.context.eventRepository.count("prerequisite")).toBe(2);
  });

  test("retention removes archived consumers before their prerequisites across batches", () => {
    using f = fixture();
    f.create("first");
    f.create("second");
    f.create("third");
    f.context.planning.add(admin, "second", "first");
    f.context.planning.add(admin, "third", "second");
    const archived = f.context.maintenance.archive(admin, {
      ids: ["first", "second", "third"], reason: "completed review",
    });
    expect(archived).toHaveLength(3);
    const cutoff = f.context.jobRepository.require("first").archivedAt! + 1;
    expect(f.context.maintenance.purge(admin, cutoff, 1)).toEqual(["third"]);
    expect(f.context.jobRepository.get("first")).not.toBeNull();
    expect(f.context.jobRepository.get("second")).not.toBeNull();
    expect(f.context.maintenance.purge(admin, cutoff, 1)).toEqual(["second"]);
    expect(f.context.maintenance.purge(admin, cutoff, 1)).toEqual(["first"]);
    expect(f.context.planning.projectPlan(reader).order).toEqual([]);
  });

  test("retention protection propagates through a chain to a nonarchived consumer", () => {
    using f = fixture();
    f.create("root");
    f.create("middle");
    f.create("live");
    f.context.planning.add(admin, "middle", "root");
    f.context.planning.add(admin, "live", "middle");
    f.context.maintenance.archive(admin, { ids: ["root", "middle"], reason: "old records" });
    const cutoff = f.context.jobRepository.require("root").archivedAt! + 1;
    expect(f.context.maintenance.purge(admin, cutoff, 10)).toEqual([]);
    expect(f.context.jobRepository.get("root")).not.toBeNull();
    expect(f.context.jobRepository.get("middle")).not.toBeNull();
    expect(f.context.jobRepository.get("live")).not.toBeNull();
  });

  test("purging a dependency set removes each archived record's evidence and events", () => {
    using f = fixture();
    f.create("first");
    f.create("second");
    f.attach("proof-first", "first");
    f.attach("proof-second", "second");
    f.context.planning.add(admin, "second", "first");
    f.context.maintenance.archive(admin, { ids: ["first", "second"], reason: "retention" });
    const cutoff = f.context.jobRepository.require("first").archivedAt! + 1;
    expect(f.context.maintenance.purge(admin, cutoff, 10)).toEqual(["second", "first"]);
    expect(f.context.evidenceRepository.get("proof-first")).toBeNull();
    expect(f.context.evidenceRepository.get("proof-second")).toBeNull();
    expect(f.context.eventRepository.count("first")).toBe(0);
    expect(f.context.eventRepository.count("second")).toBe(0);
  });
});

describe("stable retention batches", () => {
  test("independent archives with equal retention times use the job id tiebreaker", () => {
    using f = fixture();
    f.create("z-job");
    f.create("a-job");
    f.create("m-job");
    f.context.maintenance.archive(admin, {
      ids: ["z-job", "a-job", "m-job"], reason: "same review batch",
    });
    const cutoff = f.context.jobRepository.require("z-job").archivedAt! + 1;
    expect(f.context.maintenance.purge(admin, cutoff, 1)).toEqual(["a-job"]);
    expect(f.context.maintenance.purge(admin, cutoff, 1)).toEqual(["m-job"]);
    expect(f.context.maintenance.purge(admin, cutoff, 1)).toEqual(["z-job"]);
    expect(f.context.maintenance.purge(admin, cutoff, 1)).toEqual([]);
  });

  test("old consumers can be purged while a newer archived prerequisite remains", () => {
    using f = fixture();
    f.create("root");
    f.create("consumer");
    f.context.planning.add(admin, "consumer", "root");
    const old = f.context.jobs.archive(admin, "consumer", { expectedRevision: 1 });
    const newer = f.context.jobs.archive(admin, "root", { expectedRevision: 1 });
    expect(newer.archivedAt).toBeGreaterThan(old.archivedAt!);
    const removed = f.context.maintenance.purge(admin, newer.archivedAt!, 10);
    expect(removed).toEqual(["consumer"]);
    expect(f.context.jobRepository.get("root")).not.toBeNull();
    expect(f.context.jobRepository.get("consumer")).toBeNull();
    expect(f.context.planning.projectPlan(reader).order).toEqual(["root"]);
  });

  test("retention removal leaves source preferences and grants untouched", () => {
    using f = fixture();
    f.create();
    f.context.evidence.setDefaultKind(admin, "image");
    f.context.access.setDefaultPermission(admin, canonical("route_permission"));
    const archived = f.context.jobs.archive(admin, "job", { expectedRevision: 1 });
    expect(f.context.maintenance.purge(admin, archived.archivedAt! + 1, 1)).toEqual(["job"]);
    expect(f.context.evidence.getDefaultKind(admin)).toBe("image");
    expect(f.context.access.getDefaultPermission(admin)).toBe(canonical("route_permission"));
    expect(f.context.access.list(admin, reader.id)).toHaveLength(1);
    expect(f.context.grantRepository.has(reader, canonical("route_permission"))).toBe(true);
  });

  test("completed evidence is retained unchanged until administrative retention removes the job", () => {
    using f = fixture();
    f.create();
    const item = f.attach();
    f.context.jobs.transition(admin, "job", { stage: "active", expectedRevision: 1, reason: "start" });
    f.context.jobs.transition(admin, "job", { stage: "complete", expectedRevision: 2, reason: "done" });
    expect(() => f.context.evidence.remove(admin, "job", item.id, { expectedRevision: 1 })).toThrow("read only");
    expect(f.context.evidenceRepository.require(item.id)).toEqual(item);
    const archived = f.context.jobs.archive(admin, "job", { expectedRevision: 3 });
    expect(f.context.exports.project(reader, true).jobs[0]?.evidence[0]).toEqual(item);
    expect(f.context.maintenance.purge(admin, archived.archivedAt! + 1, 1)).toEqual(["job"]);
    expect(f.context.evidenceRepository.get(item.id)).toBeNull();
  });
});

test("purge scopes archives by project before scanning retention candidates", () => {
  using f = fixture();
  seedArchives(f.context, 10001, outsider.project);
  f.create("eligible");
  f.context.jobs.archive(admin, "eligible", { expectedRevision: 1 });
  expect(f.context.maintenance.purge(admin, 1002, 1)).toEqual(["eligible"]);
});

test("purge advances past ten thousand archives protected by a retained dependent", () => {
  using f = fixture();
  seedArchives(f.context, 10000);
  f.create("retained");
  f.context.db.transaction(() => {
    for (let index = 0; index < 10000; index++) {
      new DependencyRepository(f.context.db).add("retained", `archive-project-${index}`, admin.id, 3);
    }
  })();
  f.create("eligible");
  f.context.jobs.archive(admin, "eligible", { expectedRevision: 1 });
  expect(f.context.maintenance.purge(admin, 1003, 1)).toEqual(["eligible"]);
});
