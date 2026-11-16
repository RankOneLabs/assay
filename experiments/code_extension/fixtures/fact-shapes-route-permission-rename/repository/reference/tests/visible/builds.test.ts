import { describe, expect, test } from "bun:test";
import { fixture, admin, reader, outsider } from "./helpers.ts";

const start = {
  id: "attempt", sessionId: "session", worker: "worker", expectedRevision: 1,
};

describe("build lifecycle", () => {
  test("starts a build, moves the job and publishes owner state", () => {
    using f = fixture();
    f.create();
    expect(f.context.sessions.isBuildRunning("session")).toBe(false);
    const attempt = f.context.builds.start(admin, "job", start);
    expect(attempt.id).toBe("attempt");
    expect(attempt.jobId).toBe("job");
    expect(attempt.exitCode).toBeNull();
    expect(attempt.finishedAt).toBeNull();
    expect(f.context.sessions.isBuildRunning("session")).toBe(true);
    expect(f.context.jobRepository.require("job").stage).toBe("active");
    expect(f.context.builds.list(reader, "job")[0]?.running).toBe(true);
    expect(f.context.eventRepository.count("job")).toBe(2);
  });

  test("success finishes the attempt and completes the job", () => {
    using f = fixture();
    f.create();
    const attempt = f.context.builds.start(admin, "job", start);
    const finished = f.context.builds.finish(admin, "job", {
      sessionId: "session", exitCode: 0, output: "all checks passed",
    });
    expect(finished.id).toBe(attempt.id);
    expect(finished.exitCode).toBe(0);
    expect(finished.output).toBe("all checks passed");
    expect(finished.finishedAt).toBeGreaterThan(attempt.startedAt);
    expect(f.context.sessions.isBuildRunning("session")).toBe(false);
    expect(f.context.jobRepository.require("job").stage).toBe("complete");
    expect(f.context.jobRepository.require("job").revision).toBe(3);
    expect(f.context.builds.list(reader, "job")[0]?.running).toBe(false);
  });

  test("failure returns the job to queue and permits a new session", () => {
    using f = fixture();
    f.create();
    f.context.builds.start(admin, "job", start);
    f.context.builds.finish(admin, "job", {
      sessionId: "session", exitCode: 2, output: "failed compilation",
    });
    expect(f.context.jobRepository.require("job").stage).toBe("queued");
    const retry = f.context.builds.start(admin, "job", {
      id: "retry", sessionId: "retry-session", worker: "worker-2", expectedRevision: 3,
    });
    expect(retry.worker).toBe("worker-2");
    expect(f.context.sessions.isBuildRunning("retry-session")).toBe(true);
    expect(f.context.sessions.isBuildRunning("session")).toBe(false);
    expect(f.context.builds.list(reader, "job")).toHaveLength(2);
  });

  test("finished session ids cannot be reused", () => {
    using f = fixture();
    f.create();
    f.context.builds.start(admin, "job", start);
    f.context.builds.finish(admin, "job", {
      sessionId: "session", exitCode: 1, output: "retry needed",
    });
    expect(() => f.context.builds.start(admin, "job", {
      ...start, id: "another", expectedRevision: 3,
    })).toThrow("session id already used");
    expect(f.context.jobRepository.require("job").stage).toBe("queued");
    expect(f.context.sessions.isBuildRunning("session")).toBe(false);
    expect(f.context.attemptRepository.list("job")).toHaveLength(1);
  });

  test("two jobs cannot run in the same session", () => {
    using f = fixture();
    f.create("first");
    f.create("second");
    f.context.builds.start(admin, "first", start);
    expect(() => f.context.builds.start(admin, "second", {
      ...start, id: "second-attempt",
    })).toThrow("already running");
    expect(f.context.jobRepository.require("second").stage).toBe("queued");
    expect(f.context.attemptRepository.list("second")).toHaveLength(0);
    expect(f.context.sessions.isBuildRunning("session")).toBe(true);
  });

  test("stale job revisions never create an attempt or session state", () => {
    using f = fixture();
    f.create();
    f.context.jobs.patch(admin, "job", { title: "changed", expectedRevision: 1 });
    expect(() => f.context.builds.start(admin, "job", start)).toThrow("revision changed");
    expect(f.context.attemptRepository.list("job")).toHaveLength(0);
    expect(f.context.sessions.isBuildRunning("session")).toBe(false);
    expect(f.context.jobRepository.require("job").stage).toBe("queued");
  });

  test("an archived job cannot start a build", () => {
    using f = fixture();
    f.create();
    f.context.jobs.archive(admin, "job", { expectedRevision: 1 });
    expect(() => f.context.builds.start(admin, "job", {
      ...start, expectedRevision: 2,
    })).toThrow("queued job");
    expect(f.context.sessions.isBuildRunning("session")).toBe(false);
    expect(f.context.attemptRepository.list("job")).toEqual([]);
  });

  test("completion cannot be repeated", () => {
    using f = fixture();
    f.create();
    f.context.builds.start(admin, "job", start);
    const request = { sessionId: "session", exitCode: 0, output: "done" };
    f.context.builds.finish(admin, "job", request);
    expect(() => f.context.builds.finish(admin, "job", request)).toThrow("not running");
    expect(f.context.eventRepository.count("job")).toBe(3);
    expect(f.context.jobRepository.require("job").revision).toBe(3);
  });

  test("ending a session reads false even though an unfinished historical attempt remains", () => {
    using f = fixture();
    f.create();
    f.context.builds.start(admin, "job", start);
    f.context.builds.end(admin, "job", "session");
    expect(f.context.sessions.isBuildRunning("session")).toBe(false);
    expect(f.context.attemptRepository.require("attempt").finishedAt).toBeNull();
    expect(f.context.builds.list(reader, "job")[0]?.running).toBe(false);
    expect(() => f.context.builds.finish(admin, "job", {
      sessionId: "session", exitCode: 0, output: "late",
    })).toThrow("not running");
  });

  test("finishing a different job's session is refused", () => {
    using f = fixture();
    f.create("first");
    f.create("second");
    f.context.builds.start(admin, "first", start);
    expect(() => f.context.builds.finish(admin, "second", {
      sessionId: "session", exitCode: 0, output: "wrong job",
    })).toThrow("not found");
    expect(f.context.sessions.isBuildRunning("session")).toBe(true);
    expect(f.context.attemptRepository.require("attempt").exitCode).toBeNull();
  });

  test("readers and other projects cannot start or finish builds", () => {
    using f = fixture();
    f.create();
    expect(() => f.context.builds.start(reader, "job", start)).toThrow("permission");
    expect(() => f.context.builds.start(outsider, "job", start)).toThrow("another project");
    f.context.builds.start(admin, "job", start);
    expect(() => f.context.builds.finish(reader, "job", {
      sessionId: "session", exitCode: 0, output: "no",
    })).toThrow("permission");
    expect(f.context.sessions.isBuildRunning("session")).toBe(true);
  });

  test("HTTP build lifecycle exposes running status from the owner", async () => {
    using f = fixture();
    f.create();
    expect((await f.request("POST", "/jobs/job/builds", start)).status).toBe(201);
    const running = await f.request("GET", "/jobs/job/builds", undefined, reader);
    expect(await running.json()).toMatchObject([{ running: true, sessionId: "session" }]);
    const ended = await f.request("DELETE", "/jobs/job/builds/session");
    expect(ended.status).toBe(204);
    const stopped = await f.request("GET", "/jobs/job/builds", undefined, reader);
    expect(await stopped.json()).toMatchObject([{ running: false }]);
  });
});

describe("build cancellation and recovery", () => {
  test("cancelling records a durable outcome and returns the job to queue", () => {
    using f = fixture();
    f.create();
    f.context.builds.start(admin, "job", start);
    const cancelled = f.context.builds.cancel(admin, "job", "session", "operator stopped work");
    expect(cancelled.exitCode).toBe(130);
    expect(cancelled.output).toBe("operator stopped work");
    expect(cancelled.finishedAt).not.toBeNull();
    expect(f.context.jobRepository.require("job").stage).toBe("queued");
    expect(f.context.sessions.isBuildRunning("session")).toBe(false);
    const event = f.context.jobs.history(admin, "job").at(-1)!;
    expect(event.action).toBe("build.cancelled");
    expect(JSON.parse(event.detail)).toMatchObject({ sessionId: "session", reason: "operator stopped work" });
  });

  test("manual transitions cannot change a live build's stage", () => {
    using f = fixture();
    f.create();
    f.context.builds.start(admin, "job", start);
    expect(() => f.context.jobs.transition(admin, "job", {
      stage: "queued", expectedRevision: 2, reason: "bypass cancel",
    })).toThrow("live build owns");
    expect(f.context.jobRepository.require("job").stage).toBe("active");
    expect(f.context.sessions.isBuildRunning("session")).toBe(true);
    expect(f.context.eventRepository.count("job")).toBe(2);
  });

  test("cancel refuses foreign jobs, missing sessions and empty reasons", () => {
    using f = fixture();
    f.create("first");
    f.create("second");
    f.context.builds.start(admin, "first", start);
    expect(() => f.context.builds.cancel(admin, "second", "session", "wrong job")).toThrow("not found");
    expect(() => f.context.builds.cancel(admin, "first", "missing", "missing")).toThrow("not found");
    expect(() => f.context.builds.cancel(admin, "first", "session", "  ")).toThrow();
    expect(f.context.sessions.isBuildRunning("session")).toBe(true);
    expect(f.context.attemptRepository.require("attempt").exitCode).toBeNull();
  });

  test("failed cancellation events leave the build running with its original attempt", () => {
    using f = fixture();
    f.create();
    const original = f.context.builds.start(admin, "job", start);
    f.context.db.exec(`
      CREATE TRIGGER reject_cancel BEFORE INSERT ON job_events
      WHEN NEW.action = 'build.cancelled' BEGIN SELECT RAISE(ABORT, 'cancel event failed'); END;
    `);
    expect(() => f.context.builds.cancel(admin, "job", "session", "stop")).toThrow("cancel event failed");
    expect(f.context.attemptRepository.require("attempt")).toEqual(original);
    expect(f.context.sessions.isBuildRunning("session")).toBe(true);
    expect(f.context.jobRepository.require("job").stage).toBe("active");
  });

  test("recovery refuses a session still marked running by its owner", () => {
    using f = fixture();
    f.create();
    f.context.builds.start(admin, "job", start);
    expect(() => f.context.builds.recover(admin, "job", "recover")).toThrow("live session");
    expect(f.context.attemptRepository.require("attempt").finishedAt).toBeNull();
    expect(f.context.sessions.isBuildRunning("session")).toBe(true);
  });

  test("recovery closes abandoned history and requeues after live ownership ended", () => {
    using f = fixture();
    f.create();
    f.context.builds.start(admin, "job", start);
    f.context.builds.end(admin, "job", "session");
    const recovered = f.context.builds.recover(admin, "job", "process was interrupted");
    expect(recovered.job.stage).toBe("queued");
    expect(recovered.job.revision).toBe(3);
    expect(recovered.attempts).toHaveLength(1);
    expect(recovered.attempts[0]?.exitCode).toBe(255);
    expect(recovered.attempts[0]?.output).toBe("process was interrupted");
    expect(f.context.sessions.isBuildRunning("session")).toBe(false);
    expect(f.context.jobs.history(admin, "job").at(-1)?.action).toBe("build.recovered");
  });

  test("recovery requires administration and an active job", () => {
    using f = fixture();
    f.create();
    expect(() => f.context.builds.recover(admin, "job", "not active")).toThrow("active job");
    f.context.builds.start(admin, "job", start);
    f.context.builds.end(admin, "job", "session");
    expect(() => f.context.builds.recover(reader, "job", "not admin")).toThrow("permission");
    expect(() => f.context.builds.recover(outsider, "job", "foreign")).toThrow("another project");
    expect(f.context.jobRepository.require("job").stage).toBe("active");
  });

  test("output pagination reads stored text and running state through independent owners", () => {
    using f = fixture();
    f.create();
    f.context.builds.start(admin, "job", start);
    const live = f.context.builds.output(reader, "job", "attempt");
    expect(live).toMatchObject({ text: "", total: 0, nextOffset: null, running: true });
    f.context.builds.finish(admin, "job", { sessionId: "session", exitCode: 0, output: "abcdefgh" });
    const first = f.context.builds.output(reader, "job", "attempt", 0, 3);
    const second = f.context.builds.output(reader, "job", "attempt", first.nextOffset!, 3);
    const third = f.context.builds.output(reader, "job", "attempt", second.nextOffset!, 3);
    expect(first.text + second.text + third.text).toBe("abcdefgh");
    expect(first.running).toBe(false);
    expect(first.total).toBe(8);
    expect(third.nextOffset).toBeNull();
  });

  test("output bounds cannot produce invalid SQL or cross-job reads", () => {
    using f = fixture();
    f.create("first");
    f.create("second");
    f.context.builds.start(admin, "first", start);
    expect(() => f.context.builds.output(reader, "second", "attempt")).toThrow("not found");
    expect(() => f.context.builds.output(reader, "first", "attempt", -1)).toThrow("offset");
    expect(() => f.context.builds.output(reader, "first", "attempt", 0, 0)).toThrow("limit");
    expect(() => f.context.builds.output(reader, "first", "attempt", 0, 10001)).toThrow("limit");
  });

  test("build summary distinguishes unfinished history from live state", () => {
    using f = fixture();
    f.create();
    expect(f.context.builds.summary(reader, "job")).toMatchObject({ total: 0, running: 0, unfinished: 0 });
    f.context.builds.start(admin, "job", start);
    expect(f.context.builds.summary(reader, "job")).toMatchObject({ total: 1, running: 1, unfinished: 1 });
    f.context.sessions.endSession("session");
    const summary = f.context.builds.summary(reader, "job");
    expect(summary.running).toBe(0);
    expect(summary.unfinished).toBe(1);
    expect(summary.succeeded).toBe(0);
    expect(summary.failed).toBe(0);
    expect(summary.workers).toEqual(["worker"]);
  });

  test("HTTP cancellation, recovery and output use the same lifecycle guards", async () => {
    using f = fixture();
    f.create();
    f.context.builds.start(admin, "job", start);
    const cancelled = await f.request("POST", "/jobs/job/builds/session/cancel", { reason: "stop" });
    expect(cancelled.status).toBe(200);
    expect(await cancelled.json()).toMatchObject({ exitCode: 130 });
    const output = await f.request("GET", "/jobs/job/builds/attempt/output?limit=2", undefined, reader);
    expect(await output.json()).toMatchObject({ text: "st", total: 4, running: false });
    const summary = await f.request("GET", "/jobs/job/builds/summary", undefined, reader);
    expect(await summary.json()).toMatchObject({ total: 1, failed: 1, running: 0 });
    const recovery = await f.request("POST", "/jobs/job/builds/recover", { reason: "not active" });
    expect(recovery.status).toBe(409);
  });
});

describe("permissions during a live build", () => {
  test("revocation prevents finishing and cancellation until a write grant is restored", () => {
    using f = fixture();
    f.create();
    f.context.access.grant(admin, reader.id, "case_write");
    f.context.builds.start(reader, "job", start);
    f.context.access.revoke(admin, reader.id, "case_write");
    expect(() => f.context.builds.finish(reader, "job", {
      sessionId: "session", exitCode: 0, output: "not allowed",
    })).toThrow("permission");
    expect(() => f.context.builds.cancel(reader, "job", "session", "not allowed")).toThrow("permission");
    expect(f.context.sessions.isBuildRunning("session")).toBe(true);
    expect(f.context.attemptRepository.require("attempt").finishedAt).toBeNull();
    f.context.access.grant(admin, reader.id, "case_write");
    f.context.builds.finish(reader, "job", { sessionId: "session", exitCode: 0, output: "allowed" });
    expect(f.context.sessions.isBuildRunning("session")).toBe(false);
    expect(f.context.jobRepository.require("job").stage).toBe("complete");
  });

  test("metadata patches during a build preserve its session and completion preconditions", () => {
    using f = fixture();
    f.create();
    f.context.builds.start(admin, "job", start);
    const patched = f.context.jobs.patch(admin, "job", { title: "Build title", expectedRevision: 2 });
    expect(patched.revision).toBe(3);
    expect(f.context.sessions.isBuildRunning("session")).toBe(true);
    f.context.builds.finish(admin, "job", { sessionId: "session", exitCode: 0, output: "done" });
    const completed = f.context.jobs.get(admin, "job");
    expect(completed.revision).toBe(4);
    expect(completed.title).toBe("Build title");
    expect(completed.stage).toBe("complete");
    expect(f.context.eventRepository.count("job")).toBe(4);
  });

  test("failed attempts can be archived, exported and purged as historical records", () => {
    using f = fixture();
    f.create();
    f.context.builds.start(admin, "job", start);
    f.context.builds.finish(admin, "job", { sessionId: "session", exitCode: 2, output: "failed" });
    const archived = f.context.jobs.archive(admin, "job", { expectedRevision: 3 });
    const exported = f.context.exports.project(reader, true);
    expect(exported.jobs[0]?.attempts[0]?.exitCode).toBe(2);
    expect(exported.jobs[0]?.attempts[0]?.output).toBe("failed");
    expect(f.context.exports.verify(exported)).toBe(true);
    expect(f.context.maintenance.purge(admin, archived.archivedAt! + 1, 1)).toEqual(["job"]);
    expect(f.context.attemptRepository.get("attempt")).toBeNull();
    expect(f.context.sessions.isBuildRunning("session")).toBe(false);
  });
});

describe("session end and retry isolation", () => {
  test("ending one job's session leaves another job's build live", () => {
    using f = fixture();
    f.create("first");
    f.create("second");
    f.context.builds.start(admin, "first", start);
    f.context.builds.start(admin, "second", {
      id: "second-attempt", sessionId: "second-session", worker: "second-worker", expectedRevision: 1,
    });
    f.context.builds.end(admin, "first", "session");
    expect(f.context.sessions.isBuildRunning("session")).toBe(false);
    expect(f.context.sessions.isBuildRunning("second-session")).toBe(true);
    expect(f.context.builds.list(reader, "first")[0]?.running).toBe(false);
    expect(f.context.builds.list(reader, "second")[0]?.running).toBe(true);
    expect(f.context.dispatch.capacity(reader).used).toBe(1);
    expect(f.context.dispatch.capacity(reader).workers).toEqual(["second-worker"]);
  });

  test("an old session cannot finish a recovered job's new build", () => {
    using f = fixture();
    f.create();
    f.context.builds.start(admin, "job", start);
    f.context.builds.end(admin, "job", "session");
    f.context.builds.recover(admin, "job", "recover old build");
    f.context.builds.start(admin, "job", {
      id: "retry", sessionId: "retry-session", worker: "worker", expectedRevision: 3,
    });
    expect(() => f.context.builds.finish(admin, "job", {
      sessionId: "session", exitCode: 0, output: "late old output",
    })).toThrow("not running");
    expect(f.context.sessions.isBuildRunning("retry-session")).toBe(true);
    expect(f.context.attemptRepository.require("retry").finishedAt).toBeNull();
    expect(f.context.attemptRepository.require("attempt").exitCode).toBe(255);
    expect(f.context.jobRepository.require("job").stage).toBe("active");
  });

  test("output is read as a fresh projection and is never stored a second time", () => {
    using f = fixture();
    f.create();
    f.context.builds.start(admin, "job", start);
    const before = f.context.builds.output(reader, "job", "attempt");
    expect(before.text).toBe("");
    expect(before.running).toBe(true);
    f.context.builds.finish(admin, "job", { sessionId: "session", exitCode: 0, output: "new output" });
    const after = f.context.builds.output(reader, "job", "attempt");
    expect(after.text).toBe("new output");
    expect(after.running).toBe(false);
    expect(before.text).toBe("");
    expect(before.running).toBe(true);
  });
});
