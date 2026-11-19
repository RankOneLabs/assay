import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { ServiceContext } from "../../../src/context.ts";

test("fact:stage_rename_existing_state: existing_state behavior", () => {
  using context = new ServiceContext();
  const actor = { id: "admin", project: "project" };
  for (const permission of ["case_write", "case_admin", "case_read"]) context.grantRepository.grant(actor, permission as never, "bootstrap", 0);
  const job = context.jobs.create(actor, { id: "job", title: "Job", description: "Fixture", owner: "owner", project: actor.project });
  expect(context.exports.bundle(actor, job.id).job).toMatchObject({ stage: "triaged", owner: "owner" });
  context.jobs.patch(actor, job.id, { owner: "triager", priority: 5, expectedRevision: job.revision });
  expect(context.exports.bundle(actor, job.id).job).toMatchObject({ owner: "triager", priority: 5 });
  expect(() => context.jobs.list(actor, { stage: "queued" })).toThrow();
}, 30000);
