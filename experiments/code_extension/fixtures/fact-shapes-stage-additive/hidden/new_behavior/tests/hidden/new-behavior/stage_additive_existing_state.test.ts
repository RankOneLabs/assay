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
import { rmSync } from "node:fs";

test("fact:stage_additive_existing_state: existing_state behavior", () => {
  const path = `/tmp/fact-runs-${crypto.randomUUID()}.sqlite`;
  try {
    {
      using before = service({ databasePath: path });
      runOf(before, "run", ["a", "b"]);
      complete(before, "a");
      complete(before, "b");
      expect(before.runs.summary(actor, "run").stages).toMatchObject({ complete: 2, queued: 0 });
    }
    using context = service({ databasePath: path });
    expect(context.runs.summary(actor, "run")).toMatchObject({ jobs: 2, attempts: 2, passed: 2 });
    move(context, "a", "queued", "rerun");
    expect(context.runs.summary(actor, "run").stages).toMatchObject({ complete: 1, queued: 1 });
    build(context, "a", 1);
    expect(context.runs.summary(actor, "run")).toMatchObject({ attempts: 3, passed: 2, failed: 1 });
    complete(context, "a");
    expect(context.runs.get(actor, "run").status).toBe("finished");
    const again = context.runs.summary(actor, "run");
    expect(again).toMatchObject({ attempts: 4, passed: 3, failed: 1 });
    expect(again.stages).toMatchObject({ complete: 2, queued: 0 });
  } finally {
    rmSync(path, { force: true });
  }
}, 30000);
