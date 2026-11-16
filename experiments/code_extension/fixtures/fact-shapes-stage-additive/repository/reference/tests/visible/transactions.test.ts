import { describe, expect, test } from "bun:test";
import { fixture, admin } from "./helpers.ts";

/** Fail a durable event write after a business row has already been modified. */
function rejectEvents(db: import("bun:sqlite").Database): void {
  db.exec(`
    CREATE TRIGGER reject_events BEFORE INSERT ON job_events
    BEGIN SELECT RAISE(ABORT, 'seeded event failure'); END;
  `);
}

describe("business operation atomicity", () => {
  test("failed creation event rolls back the job insert", () => {
    using f = fixture();
    rejectEvents(f.context.db);
    expect(() => f.create()).toThrow("seeded event failure");
    expect(f.context.jobRepository.get("job")).toBeNull();
    expect(f.context.jobRepository.count()).toBe(0);
    expect(f.context.eventRepository.count("job")).toBe(0);
  });

  test("failed patch event restores metadata and revision", () => {
    using f = fixture();
    const original = f.create();
    rejectEvents(f.context.db);
    expect(() => f.context.jobs.patch(admin, "job", {
      title: "not committed", expectedRevision: 1,
    })).toThrow("seeded event failure");
    expect(f.context.jobRepository.require("job")).toEqual(original);
    expect(f.context.eventRepository.count("job")).toBe(1);
  });

  test("failed transition event restores stage and revision", () => {
    using f = fixture();
    const original = f.create();
    rejectEvents(f.context.db);
    expect(() => f.context.jobs.transition(admin, "job", {
      stage: "active", expectedRevision: 1, reason: "not committed",
    })).toThrow("seeded event failure");
    expect(f.context.jobRepository.require("job")).toEqual(original);
    expect(f.context.eventRepository.count("job")).toBe(1);
  });

  test("failed evidence event rolls back both attachment and digest", () => {
    using f = fixture();
    f.create();
    rejectEvents(f.context.db);
    expect(() => f.attach()).toThrow("seeded event failure");
    expect(f.context.evidenceRepository.get("evidence")).toBeNull();
    expect(f.context.evidenceRepository.count("job")).toBe(0);
    expect(f.context.eventRepository.count("job")).toBe(1);
  });

  test("failed evidence edit restores the previous digest", () => {
    using f = fixture();
    f.create();
    const original = f.attach();
    rejectEvents(f.context.db);
    expect(() => f.context.evidence.patch(admin, "job", "evidence", {
      content: "not committed", expectedRevision: 1,
    })).toThrow("seeded event failure");
    expect(f.context.evidenceRepository.require("evidence")).toEqual(original);
    expect(f.context.eventRepository.count("job")).toBe(2);
  });

  test("failed evidence removal restores the deleted item", () => {
    using f = fixture();
    f.create();
    const original = f.attach();
    rejectEvents(f.context.db);
    expect(() => f.context.evidence.remove(admin, "job", "evidence", {
      expectedRevision: 1,
    })).toThrow("seeded event failure");
    expect(f.context.evidenceRepository.require("evidence")).toEqual(original);
    expect(f.context.eventRepository.count("job")).toBe(2);
  });

  test("failed archive event restores the unarchived row", () => {
    using f = fixture();
    const original = f.create();
    rejectEvents(f.context.db);
    expect(() => f.context.jobs.archive(admin, "job", {
      expectedRevision: 1,
    })).toThrow("seeded event failure");
    expect(f.context.jobRepository.require("job")).toEqual(original);
    expect(f.context.jobRepository.count()).toBe(1);
  });

  test("failed build start leaves no running state or historical attempt", () => {
    using f = fixture();
    const original = f.create();
    rejectEvents(f.context.db);
    expect(() => f.context.builds.start(admin, "job", {
      id: "attempt", sessionId: "session", worker: "worker", expectedRevision: 1,
    })).toThrow("seeded event failure");
    expect(f.context.jobRepository.require("job")).toEqual(original);
    expect(f.context.attemptRepository.list("job")).toEqual([]);
    expect(f.context.sessions.isBuildRunning("session")).toBe(false);
  });

  test("failed build finish keeps the session running and attempt unfinished", () => {
    using f = fixture();
    f.create();
    const original = f.context.builds.start(admin, "job", {
      id: "attempt", sessionId: "session", worker: "worker", expectedRevision: 1,
    });
    rejectEvents(f.context.db);
    expect(() => f.context.builds.finish(admin, "job", {
      sessionId: "session", exitCode: 0, output: "not committed",
    })).toThrow("seeded event failure");
    expect(f.context.attemptRepository.require("attempt")).toEqual(original);
    expect(f.context.jobRepository.require("job").stage).toBe("active");
    expect(f.context.sessions.isBuildRunning("session")).toBe(true);
    expect(f.context.eventRepository.count("job")).toBe(2);
  });

  test("a late bulk error rolls back every earlier archive in the batch", () => {
    using f = fixture();
    f.create("first");
    f.create("second");
    f.context.jobs.transition(admin, "second", {
      stage: "active", expectedRevision: 1, reason: "start",
    });
    expect(() => f.context.maintenance.archive(admin, {
      ids: ["first", "second"], reason: "bulk cleanup",
    })).toThrow("active job");
    expect(f.context.jobRepository.require("first").archivedAt).toBeNull();
    expect(f.context.jobRepository.require("first").revision).toBe(1);
    expect(f.context.eventRepository.count("first")).toBe(1);
    expect(f.context.jobRepository.require("second").stage).toBe("active");
  });
});

describe("compound workflow rollback", () => {
  test("a clone failure after creation restores capacity and leaves no copied row", () => {
    using f = fixture();
    f.create("source");
    f.context.db.exec(`
      CREATE TRIGGER reject_clone BEFORE INSERT ON job_events
      WHEN NEW.action = 'job.cloned' BEGIN SELECT RAISE(ABORT, 'clone failure'); END;
    `);
    expect(() => f.context.jobs.clone(admin, "source", { id: "copy" })).toThrow("clone failure");
    expect(f.context.jobRepository.count()).toBe(1);
    expect(f.context.jobRepository.get("copy")).toBeNull();
    expect(f.context.eventRepository.count("copy")).toBe(0);
    expect(f.context.eventRepository.count("source")).toBe(1);
  });

  test("a failed copy provenance event removes the copied evidence too", () => {
    using f = fixture();
    f.create("source");
    f.create("target");
    const original = f.attach("proof", "source");
    f.context.db.exec(`
      CREATE TRIGGER reject_copy BEFORE INSERT ON job_events
      WHEN NEW.action = 'evidence.copied' BEGIN SELECT RAISE(ABORT, 'copy failure'); END;
    `);
    expect(() => f.context.evidence.copy(admin, "source", "proof", "target", "copy")).toThrow("copy failure");
    expect(f.context.evidenceRepository.get("copy")).toBeNull();
    expect(f.context.evidenceRepository.require("proof")).toEqual(original);
    expect(f.context.eventRepository.count("target")).toBe(1);
  });

  test("a failed dependency event rolls back the edge and preserves readiness", () => {
    using f = fixture();
    f.create("first");
    f.create("second");
    rejectEvents(f.context.db);
    expect(() => f.context.planning.add(admin, "second", "first")).toThrow("seeded event failure");
    expect(f.context.planning.blockers(admin, "second")).toEqual([]);
    expect(f.context.planning.projectPlan(admin).layers).toEqual([["first", "second"]]);
    expect(f.context.eventRepository.count("second")).toBe(1);
  });

  test("a failed dependency removal event restores the removed edge", () => {
    using f = fixture();
    f.create("first");
    f.create("second");
    f.context.planning.add(admin, "second", "first");
    rejectEvents(f.context.db);
    expect(() => f.context.planning.remove(admin, "second", "first")).toThrow("seeded event failure");
    expect(f.context.planning.blockers(admin, "second").map(job => job.id)).toEqual(["first"]);
    expect(f.context.eventRepository.count("second")).toBe(2);
  });

  test("failed recovery does not rewrite abandoned attempt history", () => {
    using f = fixture();
    f.create();
    const attempt = f.context.builds.start(admin, "job", {
      id: "attempt", sessionId: "session", worker: "worker", expectedRevision: 1,
    });
    f.context.sessions.endSession("session");
    rejectEvents(f.context.db);
    expect(() => f.context.builds.recover(admin, "job", "recover")).toThrow("seeded event failure");
    expect(f.context.attemptRepository.require("attempt")).toEqual(attempt);
    expect(f.context.jobRepository.require("job").stage).toBe("active");
    expect(f.context.sessions.isBuildRunning("session")).toBe(false);
  });

  test("a bulk grant database failure rolls back grants inserted earlier in the batch", () => {
    using f = fixture();
    f.context.db.exec(`
      CREATE TRIGGER reject_grant BEFORE INSERT ON grants
      WHEN NEW.principal = 'blocked' BEGIN SELECT RAISE(ABORT, 'grant failure'); END;
    `);
    expect(() => f.context.access.bulkGrant(admin, [
      { principal: "first", permission: "case_read" },
      { principal: "blocked", permission: "case_write" },
    ])).toThrow("grant failure");
    expect(f.context.access.list(admin, "first")).toEqual([]);
    expect(f.context.access.list(admin, "blocked")).toEqual([]);
  });
});
