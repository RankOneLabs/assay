import { describe, expect, test } from "bun:test";
import { fixture, admin, reader, outsider } from "./helpers.ts";
import { count } from "../../src/rollup/pieces.ts";
import type { Job } from "../../src/domain/models.ts";

type Fixture = ReturnType<typeof fixture>;

function runWith(f: Fixture, id: string, jobs: string[]) {
  f.context.runs.create(admin, { id, title: `Run ${id}` });
  for (const job of jobs) f.create(job);
  return f.context.runs.add(admin, id, { jobs });
}

function finishByHand(f: Fixture, id: string) {
  const job = f.context.jobRepository.require(id);
  if (job.stage === "queued") {
    f.context.jobs.transition(admin, id, { stage: "active", expectedRevision: job.revision, reason: "start" });
  }
  const active = f.context.jobRepository.require(id);
  return f.context.jobs.transition(admin, id, { stage: "complete", expectedRevision: active.revision, reason: "done" });
}

describe("runs", () => {
  test("a new run is running and counts the jobs added to it", () => {
    using f = fixture();
    const empty = f.context.runs.create(admin, { id: "run", title: "Nightly" });
    expect(empty).toMatchObject({ id: "run", title: "Nightly", status: "running", total: 0, open: 0, done: 0 });
    expect(empty.finishedAt).toBeNull();
    f.create("a");
    f.create("b");
    const run = f.context.runs.add(admin, "run", { jobs: ["a", "b"] });
    expect(run).toMatchObject({ status: "running", total: 2, open: 2, done: 0 });
    expect(f.context.jobRepository.require("a").runId).toBe("run");
    expect(f.context.runs.jobs(reader, "run").map(job => job.id)).toEqual(["a", "b"]);
  });

  test("a run finishes when its last job is done, and records when", () => {
    using f = fixture();
    runWith(f, "run", ["a", "b"]);
    finishByHand(f, "a");
    expect(f.context.runs.get(reader, "run")).toMatchObject({ status: "running", open: 1, done: 1 });
    expect(f.context.runs.get(reader, "run").finishedAt).toBeNull();
    const last = finishByHand(f, "b");
    const run = f.context.runs.get(reader, "run");
    expect(run).toMatchObject({ status: "finished", total: 2, open: 0, done: 2 });
    expect(run.finishedAt).toBeGreaterThanOrEqual(last.finishedAt!);
    expect(run.duration).toBe(run.finishedAt! - run.createdAt);
    expect(f.context.jobRepository.require("b").finishedAt).toBe(last.updatedAt);
  });

  test("runs are listed by their stored status", () => {
    using f = fixture();
    runWith(f, "done", ["a"]);
    runWith(f, "busy", ["b"]);
    finishByHand(f, "a");
    expect(f.context.runs.list(reader, { status: "finished" }).items.map(run => run.id)).toEqual(["done"]);
    expect(f.context.runs.list(reader, { status: "running" }).items.map(run => run.id)).toEqual(["busy"]);
    expect(f.context.runs.list(reader).total).toBe(2);
    const stored = f.context.db.query("SELECT status FROM runs WHERE id = 'done'").get();
    expect(stored).toEqual({ status: "finished" });
  });

  test("bulk moves bring each run up to date", () => {
    using f = fixture();
    runWith(f, "left", ["a", "b"]);
    runWith(f, "right", ["c"]);
    f.context.jobs.bulkTransition(admin, {
      changes: ["a", "b", "c"].map(id => ({ id, transition: { stage: "active", expectedRevision: 2, reason: "start" } })),
    });
    expect(f.context.runs.get(reader, "left")).toMatchObject({ status: "running", open: 2, done: 0 });
    f.context.jobs.bulkTransition(admin, {
      changes: ["a", "b", "c"].map(id => ({ id, transition: { stage: "complete", expectedRevision: 3, reason: "done" } })),
    });
    for (const id of ["left", "right"]) {
      const run = f.context.runs.get(reader, id);
      expect(run.status).toBe("finished");
      expect(run.open).toBe(0);
      expect(run.done).toBe(run.total);
      expect(run.finishedAt).not.toBeNull();
    }
    expect(f.context.runs.list(reader, { status: "finished" }).total).toBe(2);
  });

  test("a job's attempts roll up into the job", () => {
    using f = fixture();
    runWith(f, "run", ["a"]);
    f.context.builds.start(admin, "a", { id: "first", sessionId: "s1", worker: "w1", expectedRevision: 2 });
    expect(f.context.jobRepository.require("a").rollup).toEqual({ attempts: 1, running: true, outcome: null });
    f.context.builds.finish(admin, "a", { sessionId: "s1", exitCode: 2, output: "failed" });
    expect(f.context.jobRepository.require("a").rollup).toEqual({ attempts: 1, running: false, outcome: "failed" });
    expect(f.context.runs.get(reader, "run")).toMatchObject({ status: "running", open: 1, done: 0 });
    f.context.builds.start(admin, "a", { id: "second", sessionId: "s2", worker: "w2", expectedRevision: 4 });
    f.context.builds.cancel(admin, "a", "s2", "operator stop");
    expect(f.context.jobRepository.require("a").rollup).toEqual({ attempts: 2, running: false, outcome: "failed" });
  });

  test("a successful build completes a job and rolls its attempt up", () => {
    using f = fixture();
    f.create("solo");
    f.context.builds.start(admin, "solo", { id: "attempt", sessionId: "session", worker: "w", expectedRevision: 1 });
    f.context.builds.finish(admin, "solo", { sessionId: "session", exitCode: 0, output: "ok" });
    const job = f.context.jobRepository.require("solo");
    expect(job.stage).toBe("complete");
    expect(job.rollup).toEqual({ attempts: 1, running: false, outcome: "passed" });
    expect(job.finishedAt).toBe(job.updatedAt);
  });

  test("a summary adds up a run's jobs and attempts and is stored once the run finishes", () => {
    using f = fixture();
    runWith(f, "run", ["a", "b"]);
    f.context.builds.start(admin, "a", { id: "x", sessionId: "s1", worker: "w1", expectedRevision: 2 });
    f.context.builds.finish(admin, "a", { sessionId: "s1", exitCode: 1, output: "no" });
    const running = f.context.runs.summary(reader, "run");
    expect(running).toMatchObject({ runId: "run", jobs: 2, attempts: 1, passed: 0, failed: 1, workers: ["w1"] });
    expect(running.stages.queued).toBe(2);
    expect(f.context.db.query("SELECT COUNT(*) AS count FROM run_summaries").get()).toEqual({ count: 0 });
    finishByHand(f, "a");
    finishByHand(f, "b");
    const finished = f.context.runs.summary(reader, "run");
    expect(finished.stages.complete).toBe(2);
    expect(finished.stages.queued).toBe(0);
    expect(f.context.db.query("SELECT COUNT(*) AS count FROM run_summaries").get()).toEqual({ count: 1 });
    expect(f.context.runs.summary(reader, "run")).toEqual(finished);
  });

  test("a finished run takes no new jobs", () => {
    using f = fixture();
    runWith(f, "run", ["a"]);
    finishByHand(f, "a");
    f.create("late");
    expect(() => f.context.runs.add(admin, "run", { jobs: ["late"] })).toThrow("finished run");
    expect(() => f.create("direct", { runId: "run" })).toThrow("finished run");
    expect(f.context.runs.get(reader, "run")).toMatchObject({ status: "finished", total: 1 });
  });

  test("jobs can be created straight into a run", () => {
    using f = fixture();
    f.context.runs.create(admin, { id: "run", title: "Run" });
    f.create("a", { runId: "run" });
    expect(f.context.runs.get(reader, "run")).toMatchObject({ total: 1, open: 1, done: 0 });
    expect(() => f.create("b", { runId: "missing" })).toThrow();
  });

  test("a job belongs to at most one run and runs stay in their project", () => {
    using f = fixture();
    runWith(f, "first", ["a"]);
    f.context.runs.create(admin, { id: "second", title: "Second" });
    expect(() => f.context.runs.add(admin, "second", { jobs: ["a"] })).toThrow("already belongs");
    expect(() => f.context.runs.get(outsider, "first")).toThrow("another project");
    expect(() => f.context.runs.create(reader, { id: "nope", title: "Nope" })).toThrow();
  });

  test("a level's declaration can gain a field built from the existing pieces", () => {
    using f = fixture();
    f.context.rollups.declare("run", "active", count<Job>(job => job.stage === "active"));
    runWith(f, "run", ["a", "b"]);
    f.context.jobs.transition(admin, "a", { stage: "active", expectedRevision: 2, reason: "start" });
    expect(f.context.runs.get(reader, "run") as unknown as Record<string, unknown>).toMatchObject({ active: 1, total: 2 });
    expect(f.context.rollups.compute("run", "run")).toEqual({ ...f.context.runRepository.require("run").state });
  });

  test("purging archived jobs keeps jobs that belong to a run", () => {
    using f = fixture();
    runWith(f, "run", ["kept"]);
    f.create("gone");
    f.context.jobs.archive(admin, "kept", { expectedRevision: 2 });
    f.context.jobs.archive(admin, "gone", { expectedRevision: 1 });
    const purged = f.context.maintenance.purge(admin, f.context.jobRepository.require("gone").archivedAt! + 1, 10);
    expect(purged).toEqual(["gone"]);
    expect(f.context.runs.get(reader, "run").total).toBe(1);
  });

  test("runs are served over HTTP", async () => {
    using f = fixture();
    const created = await f.request("POST", "/runs", { id: "run", title: "Over HTTP" });
    expect(created.status).toBe(201);
    f.create("a");
    expect((await f.request("POST", "/runs/run/jobs", { jobs: ["a"] })).status).toBe(200);
    const run = await (await f.request("GET", "/runs/run", undefined, reader)).json() as { total: number };
    expect(run.total).toBe(1);
    const listed = await (await f.request("GET", "/runs?status=running", undefined, reader)).json() as { total: number };
    expect(listed.total).toBe(1);
    expect((await f.request("GET", "/runs/run/summary", undefined, reader)).status).toBe(200);
  });
});
