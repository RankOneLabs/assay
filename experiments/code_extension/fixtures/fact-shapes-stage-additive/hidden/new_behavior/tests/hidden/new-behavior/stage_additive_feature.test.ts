import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { ServiceContext } from "../../../src/context.ts";

const actor = { id: "admin", project: "project" };

function service(config: unknown = {}): ServiceContext {
  const context = new ServiceContext(config);
  for (const permission of ["case_read", "case_write", "case_admin"]) {
    context.grantRepository.grant(actor, permission as never, "bootstrap", 0);
  }
  return context;
}

function importJob(context: ServiceContext, id: string) {
  const input = { version: 1, entries: [{ job: { id, title: `Imported ${id}`, owner: "owner", project: actor.project } }] };
  return context.imports.commit(actor, input, context.imports.preview(actor, input).digest)[0]!;
}

function direct(context: ServiceContext, id: string) {
  return context.jobs.create(actor, { id, title: `Direct ${id}`, owner: "owner", project: actor.project });
}

test("feature:stage_additive_import_triage: imported jobs start in triaged", () => {
  using context = service();
  expect(importJob(context, "imported").stage).toBe("triaged" as never);
  expect(context.jobs.get(actor, "imported").stage).toBe("triaged" as never);
  expect(direct(context, "direct").stage).toBe("queued");
}, 30000);

test("feature:stage_additive_release: a triaged job is updated and released with its reason kept", () => {
  using context = service();
  const job = importJob(context, "imported");
  const patched = context.jobs.patch(actor, job.id, { priority: 7, owner: "triager", expectedRevision: job.revision });
  const released = context.jobs.transition(actor, job.id, {
    stage: "queued", expectedRevision: patched.revision, reason: "looks valid",
  });
  expect(released).toMatchObject({ stage: "queued", priority: 7, owner: "triager" });
  expect(JSON.stringify(context.jobs.history(actor, job.id))).toContain("looks valid");
  expect(context.planning.ready(actor).map(item => item.id)).toContain(job.id);
}, 30000);

test("feature:stage_additive_reject: a rejected job is completed with its reason kept", () => {
  using context = service();
  const job = importJob(context, "imported");
  const rejected = context.jobs.transition(actor, job.id, {
    stage: "complete", expectedRevision: job.revision, reason: "duplicate report",
  });
  expect(rejected.stage).toBe("complete");
  expect(JSON.stringify(context.jobs.history(actor, job.id))).toContain("duplicate report");
}, 30000);

test("feature:stage_additive_triage_moves: no other move enters or leaves triaged", () => {
  using context = service();
  const job = importJob(context, "imported");
  expect(() => context.jobs.transition(actor, job.id, {
    stage: "active", expectedRevision: job.revision, reason: "skip triage",
  })).toThrow();
  const other = direct(context, "direct");
  expect(() => context.jobs.transition(actor, other.id, {
    stage: "triaged", expectedRevision: other.revision, reason: "send back",
  })).toThrow();
  expect(context.jobs.get(actor, job.id).stage).toBe("triaged" as never);
  expect(context.jobs.get(actor, other.id).stage).toBe("queued");
}, 30000);

test("feature:stage_additive_triage_not_built: triaged jobs are never picked for a build", () => {
  using context = service();
  const job = importJob(context, "imported");
  expect(context.planning.ready(actor)).toEqual([]);
  expect(() => context.builds.start(actor, job.id, {
    id: "attempt", sessionId: "session", worker: "worker", expectedRevision: job.revision,
  })).toThrow();
  expect(context.dispatch.next(actor, { id: "attempt", sessionId: "session", worker: "worker" })).toBeNull();
  expect(context.jobs.get(actor, job.id).stage).toBe("triaged" as never);
}, 30000);
