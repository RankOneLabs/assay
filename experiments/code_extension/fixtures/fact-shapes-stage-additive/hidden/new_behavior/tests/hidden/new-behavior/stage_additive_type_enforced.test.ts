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

test("fact:stage_additive_type_enforced: type_enforced behavior", () => {
  using context = service();
  runOf(context, "run", ["a", "b"]);
  build(context, "a", 0);
  expect(context.jobRepository.require("a").stage).toBe("in_review" as never);
  expect(context.runs.get(actor, "run")).toMatchObject({ status: "running", total: 2, open: 2, done: 0 });
  move(context, "a", "complete", "approved");
  build(context, "b", 0);
  expect(context.runs.get(actor, "run")).toMatchObject({ status: "running", total: 2, open: 1, done: 1 });
  move(context, "b", "complete", "approved");
  expect(context.runs.get(actor, "run")).toMatchObject({ status: "finished", open: 0, done: 2 });
}, 30000);
