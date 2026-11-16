import { describe, expect, test } from "bun:test";
import { fixture, admin, outsider, writer } from "./helpers.ts";

describe("job lifecycle invariants", () => {
  test("creation fills defaults and records a single event", () => {
    using f = fixture();
    const job = f.create("first");
    expect(job.stage).toBe("queued");
    expect(job.revision).toBe(1);
    expect(job.priority).toBe(0);
    expect(job.archivedAt).toBeNull();
    expect(job.createdAt).toBe(job.updatedAt);
    const history = f.context.jobs.history(admin, job.id);
    expect(history).toHaveLength(1);
    expect(history[0]?.actor).toBe(admin.id);
    expect(JSON.parse(history[0]!.detail)).toEqual({ title: "Job first" });
  });

  test("duplicate ids preserve both the original row and its history", () => {
    using f = fixture();
    const original = f.create();
    expect(() => f.create("job", { title: "replacement" })).toThrow("already exists");
    expect(f.context.jobRepository.require("job")).toEqual(original);
    expect(f.context.eventRepository.count("job")).toBe(1);
    expect(f.context.jobRepository.count()).toBe(1);
  });

  test("patch requires a changed field and a current revision", () => {
    using f = fixture();
    f.create();
    expect(() => f.context.jobs.patch(admin, "job", { expectedRevision: 1 })).toThrow();
    expect(() => f.context.jobs.patch(admin, "job", {
      title: "stale", expectedRevision: 2,
    })).toThrow("revision changed");
    expect(f.context.jobRepository.require("job").revision).toBe(1);
    expect(f.context.eventRepository.count("job")).toBe(1);
  });

  test("patching does not reset omitted values or discard zero priority", () => {
    using f = fixture();
    f.create("job", { priority: 9, description: "keep" });
    const patched = f.context.jobs.patch(admin, "job", {
      priority: 0, expectedRevision: 1,
    });
    expect(patched.priority).toBe(0);
    expect(patched.description).toBe("keep");
    expect(patched.title).toBe("Job job");
    expect(patched.revision).toBe(2);
    expect(patched.updatedAt).toBeGreaterThan(patched.createdAt);
  });

  test("transition records source, destination and user reason", () => {
    using f = fixture();
    f.create();
    const active = f.context.jobs.transition(admin, "job", {
      stage: "active", expectedRevision: 1, reason: "worker selected",
    });
    expect(active.stage).toBe("active");
    const event = f.context.jobs.history(admin, "job")[1]!;
    expect(event.action).toBe("job.transitioned");
    expect(JSON.parse(event.detail)).toEqual({
      from: "queued", to: "active", reason: "worker selected",
    });
  });

  test("queued jobs cannot skip directly to completion", () => {
    using f = fixture();
    f.create();
    expect(() => f.context.jobs.transition(admin, "job", {
      stage: "complete", expectedRevision: 1, reason: "skip",
    })).toThrow("cannot move");
    expect(f.context.jobRepository.require("job").stage).toBe("queued");
    expect(f.context.eventRepository.count("job")).toBe(1);
  });

  test("active jobs can return to the queue and advance again", () => {
    using f = fixture();
    f.create();
    f.context.jobs.transition(admin, "job", {
      stage: "active", expectedRevision: 1, reason: "start",
    });
    f.context.jobs.transition(admin, "job", {
      stage: "queued", expectedRevision: 2, reason: "retry",
    });
    const active = f.context.jobs.transition(admin, "job", {
      stage: "active", expectedRevision: 3, reason: "restart",
    });
    expect(active.revision).toBe(4);
    expect(f.context.eventRepository.count("job")).toBe(4);
  });

  test("completion freezes mutable metadata", () => {
    using f = fixture();
    f.create();
    f.context.jobs.transition(admin, "job", {
      stage: "active", expectedRevision: 1, reason: "start",
    });
    f.context.jobs.transition(admin, "job", {
      stage: "complete", expectedRevision: 2, reason: "done",
    });
    expect(() => f.context.jobs.patch(admin, "job", {
      title: "changed", expectedRevision: 3,
    })).toThrow("read only");
    expect(f.context.jobRepository.require("job").title).toBe("Job job");
    expect(f.context.eventRepository.count("job")).toBe(3);
  });

  test("archive and restore preserve business stage", () => {
    using f = fixture();
    f.create();
    const archived = f.context.jobs.archive(admin, "job", { expectedRevision: 1 });
    expect(archived.archivedAt).not.toBeNull();
    expect(archived.stage).toBe("queued");
    expect(f.context.jobRepository.count()).toBe(0);
    const restored = f.context.jobs.restore(admin, "job", { expectedRevision: 2 });
    expect(restored.archivedAt).toBeNull();
    expect(restored.stage).toBe("queued");
    expect(restored.revision).toBe(3);
    expect(f.context.jobRepository.count()).toBe(1);
  });

  test("archived jobs cannot be patched or moved", () => {
    using f = fixture();
    f.create();
    f.context.jobs.archive(admin, "job", { expectedRevision: 1 });
    expect(() => f.context.jobs.patch(admin, "job", {
      title: "no", expectedRevision: 2,
    })).toThrow("read only");
    expect(() => f.context.jobs.transition(admin, "job", {
      stage: "active", expectedRevision: 2, reason: "no",
    })).toThrow("read only");
    expect(f.context.eventRepository.count("job")).toBe(2);
  });

  test("active jobs cannot be archived", () => {
    using f = fixture();
    f.create();
    f.context.jobs.transition(admin, "job", {
      stage: "active", expectedRevision: 1, reason: "start",
    });
    expect(() => f.context.jobs.archive(admin, "job", { expectedRevision: 2 })).toThrow("active");
    expect(f.context.jobRepository.require("job").archivedAt).toBeNull();
  });

  test("project limits count only unarchived jobs", () => {
    using f = fixture({ maxJobs: 1 });
    f.create("first");
    expect(() => f.create("second")).toThrow("limit");
    f.context.jobs.archive(admin, "first", { expectedRevision: 1 });
    f.create("second");
    expect(() => f.context.jobs.restore(admin, "first", {
      expectedRevision: 2,
    })).toThrow("limit");
    expect(f.context.jobRepository.count()).toBe(1);
  });

  test("creation refuses a project spoof even for an administrator", () => {
    using f = fixture();
    expect(() => f.create("foreign", { project: "other" })).toThrow("another project");
    expect(f.context.jobRepository.get("foreign")).toBeNull();
    expect(() => f.context.jobs.get(outsider, "foreign")).toThrow("not found");
  });

  test("write grants do not imply administrative grants", () => {
    using f = fixture();
    f.create();
    expect(() => f.context.jobs.archive(writer, "job", { expectedRevision: 1 })).toThrow("permission");
    expect(() => f.context.jobs.restore(writer, "job", { expectedRevision: 1 })).toThrow("permission");
    expect(f.context.jobRepository.require("job").archivedAt).toBeNull();
  });
});

describe("compound job commands", () => {
  test("clone copies business metadata into a new queued revision", () => {
    using f = fixture();
    f.create("source", { priority: 40, description: "Keep this", owner: "original" });
    f.context.jobs.transition(admin, "source", {
      stage: "active", expectedRevision: 1, reason: "source work",
    });
    const cloned = f.context.jobs.clone(admin, "source", { id: "copy" });
    expect(cloned.id).toBe("copy");
    expect(cloned.title).toBe("Job source");
    expect(cloned.description).toBe("Keep this");
    expect(cloned.priority).toBe(40);
    expect(cloned.owner).toBe("original");
    expect(cloned.stage).toBe("queued");
    expect(cloned.revision).toBe(1);
    expect(cloned.archivedAt).toBeNull();
    expect(f.context.jobRepository.require("source").stage).toBe("active");
    const event = f.context.jobs.history(admin, "copy").at(-1)!;
    expect(event.action).toBe("job.cloned");
    expect(JSON.parse(event.detail)).toEqual({ sourceId: "source", sourceRevision: 2 });
  });

  test("clone overrides title and owner without copying build or evidence state", () => {
    using f = fixture();
    f.create("source");
    f.attach("proof", "source");
    f.context.builds.start(admin, "source", {
      id: "attempt", sessionId: "session", worker: "worker", expectedRevision: 1,
    });
    const cloned = f.context.jobs.clone(admin, "source", {
      id: "copy", title: "  New task  ", owner: "new-owner",
    });
    expect(cloned.title).toBe("New task");
    expect(cloned.owner).toBe("new-owner");
    expect(f.context.evidenceRepository.list("copy")).toEqual([]);
    expect(f.context.attemptRepository.list("copy")).toEqual([]);
    expect(f.context.sessions.isBuildRunning("session")).toBe(true);
    expect(f.context.jobRepository.require("source").revision).toBe(2);
  });

  test("clone honors capacity, unique ids and project isolation", () => {
    using f = fixture({ maxJobs: 2 });
    f.create("source");
    f.create("occupied");
    expect(() => f.context.jobs.clone(admin, "source", { id: "copy" })).toThrow("limit");
    expect(f.context.jobRepository.get("copy")).toBeNull();
    expect(() => f.context.jobs.clone(outsider, "source", { id: "foreign" })).toThrow("another project");
    expect(f.context.jobRepository.get("foreign")).toBeNull();
  });

  test("bulk patch applies distinct fields and preserves unrelated metadata", () => {
    using f = fixture();
    f.create("first", { description: "Keep" });
    f.create("second", { priority: 8 });
    const changed = f.context.jobs.bulkPatch(admin, {
      reason: "rebalance ownership",
      changes: [
        { id: "first", patch: { owner: "new-owner", expectedRevision: 1 } },
        { id: "second", patch: { priority: 0, expectedRevision: 1 } },
      ],
    });
    expect(changed.map(job => job.revision)).toEqual([2, 2]);
    expect(changed[0]?.owner).toBe("new-owner");
    expect(changed[0]?.description).toBe("Keep");
    expect(changed[1]?.priority).toBe(0);
    expect(f.context.jobs.history(admin, "first").at(-1)?.action).toBe("job.bulk_patched");
    expect(f.context.eventRepository.count("second")).toBe(3);
  });

  test("bulk patch rolls back earlier writes when a late revision is stale", () => {
    using f = fixture();
    const first = f.create("first");
    f.create("second");
    expect(() => f.context.jobs.bulkPatch(admin, {
      reason: "cannot commit",
      changes: [
        { id: "first", patch: { title: "uncommitted", expectedRevision: 1 } },
        { id: "second", patch: { title: "stale", expectedRevision: 8 } },
      ],
    })).toThrow("revision changed");
    expect(f.context.jobRepository.require("first")).toEqual(first);
    expect(f.context.eventRepository.count("first")).toBe(1);
    expect(f.context.jobRepository.require("second").revision).toBe(1);
  });

  test("bulk transition applies each reason and rejects repeated ids", () => {
    using f = fixture();
    f.create("first");
    f.create("second");
    const changed = f.context.jobs.bulkTransition(admin, {
      changes: [
        { id: "first", transition: { stage: "active", expectedRevision: 1, reason: "worker one" } },
        { id: "second", transition: { stage: "active", expectedRevision: 1, reason: "worker two" } },
      ],
    }, true);
    expect(changed.every(job => job.stage === "active")).toBe(true);
    expect(JSON.parse(f.context.jobs.history(admin, "second").at(-1)!.detail).reason).toBe("worker two");
    expect(() => f.context.jobs.bulkTransition(admin, {
      changes: [
        { id: "first", transition: { stage: "complete", expectedRevision: 2, reason: "one" } },
        { id: "first", transition: { stage: "queued", expectedRevision: 3, reason: "two" } },
      ],
    })).toThrow("duplicate jobs");
    expect(f.context.jobRepository.require("first").stage).toBe("active");
  });

  test("bulk transitions are atomic when a late stage edge is forbidden", () => {
    using f = fixture();
    f.create("first");
    f.create("second");
    expect(() => f.context.jobs.bulkTransition(admin, {
      changes: [
        { id: "first", transition: { stage: "active", expectedRevision: 1, reason: "start" } },
        { id: "second", transition: { stage: "complete", expectedRevision: 1, reason: "skip" } },
      ],
    })).toThrow("cannot move");
    expect(f.context.jobRepository.require("first").stage).toBe("queued");
    expect(f.context.jobRepository.require("first").revision).toBe(1);
    expect(f.context.eventRepository.count("first")).toBe(1);
  });

  test("comparison identifies business differences without treating ids as metadata changes", () => {
    using f = fixture();
    f.create("source");
    f.context.jobs.clone(admin, "source", { id: "copy", title: "Different" });
    const result = f.context.jobs.compare(admin, "source", "copy");
    expect(result.left).toEqual({ id: "source", revision: 1 });
    expect(result.right).toEqual({ id: "copy", revision: 1 });
    expect(result.changes).toEqual([{ field: "title", before: "Job source", after: "Different" }]);
    expect(f.context.jobs.compare(admin, "source", "source").changes).toEqual([]);
  });

  test("timeline uses persisted event sequence and does not invent lifecycle changes", () => {
    using f = fixture();
    f.create();
    f.context.jobs.patch(admin, "job", { title: "New title", expectedRevision: 1 });
    f.context.jobs.transition(admin, "job", { stage: "active", expectedRevision: 2, reason: "start" });
    const timeline = f.context.jobs.timeline(admin, "job");
    expect(timeline.eventCount).toBe(3);
    expect(timeline.revision).toBe(3);
    expect(timeline.stage).toBe("active");
    expect(timeline.actors).toEqual([admin.id]);
    expect(timeline.transitions).toHaveLength(1);
    expect(timeline.transitions[0]?.transition).toEqual({ from: "queued", to: "active", reason: "start" });
    expect(timeline.updatedAt).toBeGreaterThan(timeline.createdAt);
  });

  test("compound HTTP routes pass through validation and transactional services", async () => {
    using f = fixture();
    f.create("source");
    const cloned = await f.request("POST", "/jobs/source/clone", { id: "copy" });
    expect(cloned.status).toBe(201);
    const patched = await f.request("POST", "/jobs/bulk/patch", {
      reason: "batch",
      changes: [{ id: "copy", patch: { title: "Changed", expectedRevision: 1 } }],
    });
    expect(patched.status).toBe(200);
    expect(await patched.json()).toMatchObject([{ id: "copy", title: "Changed", revision: 2 }]);
    const compared = await f.request("GET", "/jobs/source/compare/copy");
    expect(await compared.json()).toMatchObject({ changes: [{ field: "title" }] });
    const timeline = await f.request("GET", "/jobs/copy/timeline");
    expect(await timeline.json()).toMatchObject({ eventCount: 4, revision: 2 });
  });
});
