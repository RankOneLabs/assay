import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { ServiceContext } from "../../../src/context.ts";

const actor = { id: "admin", project: "project" };

function service(config: unknown = {}): ServiceContext {
  let clock = 1000;
  const context = new ServiceContext(config, () => clock++);
  for (const permission of ["case_read", "case_write", "case_admin"]) {
    context.grantRepository.grant(actor, permission as never, "bootstrap", 0);
  }
  return context;
}

function runOf(context: ServiceContext, id: string, jobs: string[]): void {
  context.runs.create(actor, { id, title: `Run ${id}` });
  for (const job of jobs) {
    context.jobs.create(actor, { id: job, title: `Job ${job}`, owner: "owner", project: actor.project, runId: id });
  }
}

function move(context: ServiceContext, id: string, stage: string, reason = "moved") {
  const job = context.jobRepository.require(id);
  return context.jobs.transition(actor, id, { stage, expectedRevision: job.revision, reason });
}

function moveAll(context: ServiceContext, ids: string[], stage: string, reason = "moved") {
  return context.jobs.bulkTransition(actor, {
    changes: ids.map(id => ({
      id, transition: { stage, expectedRevision: context.jobRepository.require(id).revision, reason },
    })),
  });
}

/** Start an attempt on a queued job and finish it with this exit code. */
function build(context: ServiceContext, id: string, exitCode: number): void {
  const job = context.jobRepository.require(id);
  const session = `${id}-${job.revision}`;
  context.builds.start(actor, id, { id: session, sessionId: session, worker: "worker", expectedRevision: job.revision });
  context.builds.finish(actor, id, { sessionId: session, exitCode, output: exitCode === 0 ? "passed" : "failed" });
}

/** Pass a queued job's build, then approve its review. */
function complete(context: ServiceContext, id: string): void {
  build(context, id, 0);
  move(context, id, "complete", "approved");
}
import type { Job, Run } from "../../../src/domain/models.ts";
import { any, count, when } from "../../../src/rollup/pieces.ts";

type State = Record<string, unknown>;

function reasons(context: ServiceContext, id: string): string[] {
  return context.jobs.history(actor, id).map(event => String((JSON.parse(event.detail) as { reason?: string }).reason));
}

/** Every stored job and run equals what its children say, recomputed here from the leaves. */
function expectWholeNest(context: ServiceContext): void {
  const runs = context.db.query<{ id: string }, []>("SELECT id FROM runs").all().map(row => context.runRepository.require(row.id));
  for (const run of runs as Run[]) {
    const jobs = context.jobRepository.inRun(run.id);
    for (const job of jobs) {
      const attempts = context.attemptRepository.list(job.id);
      const ended = attempts.filter(attempt => attempt.finishedAt !== null)
        .sort((left, right) => left.finishedAt! - right.finishedAt!);
      const last = ended.at(-1);
      expect(job.rollup).toEqual({
        attempts: attempts.length,
        running: attempts.some(attempt => attempt.finishedAt === null),
        outcome: last === undefined ? null : last.exitCode === 0 ? "passed" : "failed",
      });
      expect(job.finishedAt === null).toBe(job.stage !== "complete");
    }
    const done = jobs.filter(job => job.stage === "complete").length;
    const finished = jobs.length > 0 && done === jobs.length;
    expect(run.state).toMatchObject({
      total: jobs.length, open: jobs.length - done, done, status: finished ? "finished" : "running",
    });
    expect(run.finishedAt === null).toBe(!finished);
    if (finished) {
      for (const job of jobs) expect(run.finishedAt!).toBeGreaterThanOrEqual(job.finishedAt!);
    }
    expect(context.db.query("SELECT status FROM runs WHERE id = ?").get(run.id)).toEqual({ status: run.state.status });
    const summary = context.runs.summary(actor, run.id);
    expect(summary.jobs).toBe(jobs.length);
    for (const stage of new Set(jobs.map(job => job.stage))) {
      expect(summary.stages[stage]).toBe(jobs.filter(job => job.stage === stage).length);
    }
  }
}

test("feature:stage_additive_review: a passing build of a job in a run waits for review, approval completes it, a send-back returns it to active with its reason, and a completed job can be re-queued", () => {
  using context = service();
  runOf(context, "run", ["a", "b"]);
  context.jobs.create(actor, { id: "solo", title: "Solo", owner: "owner", project: actor.project });
  build(context, "solo", 0);
  expect(context.jobRepository.require("solo").stage).toBe("complete");
  build(context, "a", 0);
  expect(context.jobRepository.require("a").stage).toBe("in_review" as never);
  move(context, "a", "active", "needs a test");
  expect(context.jobRepository.require("a").stage).toBe("active");
  expect(reasons(context, "a")).toContain("needs a test");
  move(context, "a", "queued", "rework");
  complete(context, "a");
  complete(context, "b");
  expect(context.jobRepository.require("a").stage).toBe("complete");
  expect(context.runs.get(actor, "run").status).toBe("finished");
  move(context, "b", "queued", "check again");
  expect(context.jobRepository.require("b").stage).toBe("queued");
  build(context, "b", 0);
  expect(context.jobRepository.require("b").stage).toBe("in_review" as never);
}, 30000);

test("feature:stage_additive_whole_nest: every stored run and job equals a recomputation from its children after review, send-back, approval and re-queue, single and in bulk", () => {
  using context = service();
  runOf(context, "first", ["a", "b", "c"]);
  runOf(context, "second", ["d", "e"]);
  build(context, "a", 1);
  build(context, "a", 0);
  for (const id of ["b", "c", "d", "e"]) build(context, id, 0);
  expectWholeNest(context);
  moveAll(context, ["b", "d"], "active", "send back together");
  move(context, "c", "active", "send back");
  expectWholeNest(context);
  moveAll(context, ["a", "e"], "complete", "approved together");
  moveAll(context, ["b", "c", "d"], "queued", "rework");
  for (const id of ["b", "c", "d"]) complete(context, id);
  expectWholeNest(context);
  move(context, "a", "queued", "rerun");
  moveAll(context, ["d", "e"], "queued", "rerun together");
  expectWholeNest(context);
  for (const id of ["a", "d", "e"]) build(context, id, 0);
  moveAll(context, ["a", "d"], "complete", "approved together");
  move(context, "e", "active", "send back");
  expectWholeNest(context);
}, 30000);

test("feature:stage_additive_extension: a run field declared from the existing pieces stays accurate after send-back and re-queue", () => {
  using context = service();
  context.rollups.declare("run", "inReview", count<Job>(job => job.stage === ("in_review" as never)));
  context.rollups.declare("run", "review", when(any<Job>(job => job.stage === ("in_review" as never)), "pending", "clear"));
  runOf(context, "run", ["a", "b", "c"]);
  const check = (inReview: number) => {
    const stored = context.runRepository.require("run").state as unknown as State;
    expect(stored.inReview).toBe(inReview);
    expect(stored.review).toBe(inReview > 0 ? "pending" : "clear");
    expect(context.rollups.compute("run", "run")).toEqual({ ...stored });
  };
  for (const id of ["a", "b", "c"]) build(context, id, 0);
  check(3);
  moveAll(context, ["a", "b"], "active", "send back together");
  check(1);
  move(context, "c", "active", "send back");
  check(0);
  moveAll(context, ["a", "b", "c"], "queued", "rework");
  for (const id of ["a", "b", "c"]) build(context, id, 0);
  check(3);
  moveAll(context, ["a", "b", "c"], "complete", "approved together");
  check(0);
  move(context, "a", "queued", "rerun");
  build(context, "a", 0);
  check(1);
  move(context, "a", "active", "send back");
  check(0);
}, 30000);
