import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { ServiceContext } from "../../../src/context.ts";

test("fact:stage_rename_existing_state: existing_state behavior", () => {
  using context = new ServiceContext();
  const actor = { id: "admin", project: "project" };
  for (const permission of ["case_write", "case_admin", "case_read"]) context.grantRepository.grant(actor, permission as never, "bootstrap", 0);
  const job = context.jobs.create(actor, { id: "job", title: "Job", description: "Fixture", owner: "owner", project: actor.project });
  context.builds.start(actor, job.id, { id: "attempt", sessionId: "session", worker: "worker", expectedRevision: job.revision });
  context.jobRepository.transition(job.id, "triaged" as never, 2, 2);
  expect(context.builds.list(actor, job.id)[0]?.running).toBe(true);
  context.sessions.endSession("session");
  expect(context.builds.list(actor, job.id)[0]?.running).toBe(false);
  expect(() => context.jobs.list(actor, { stage: "queued" })).toThrow();
}, 30000);
