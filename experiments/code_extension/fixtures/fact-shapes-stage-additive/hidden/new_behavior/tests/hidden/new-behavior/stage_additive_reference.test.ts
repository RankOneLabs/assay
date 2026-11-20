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

test("fact:stage_additive_reference: reference behavior", () => {
  using context = service();
  runOf(context, "run", ["a", "b"]);
  complete(context, "a");
  complete(context, "b");
  expect(context.runs.get(actor, "run").status).toBe("finished");
  move(context, "b", "queued", "flaky result");
  expect(context.runs.get(actor, "run")).toMatchObject({ status: "running", total: 2, open: 1, done: 1 });
  complete(context, "b");
  expect(context.runs.get(actor, "run")).toMatchObject({ status: "finished", open: 0, done: 2 });
  moveAll(context, ["a", "b"], "queued", "rerun together");
  expect(context.runs.get(actor, "run")).toMatchObject({ status: "running", open: 2, done: 0 });
}, 30000);
