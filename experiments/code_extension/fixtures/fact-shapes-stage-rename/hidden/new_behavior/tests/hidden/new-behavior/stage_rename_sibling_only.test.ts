import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { ServiceContext } from "../../../src/context.ts";

test("fact:stage_rename_sibling_only: sibling_only behavior", () => {
  using context = new ServiceContext();
  const actor = { id: "admin", project: "project" };
  for (const permission of ["case_read", "case_write", "case_admin"]) context.grantRepository.grant(actor, permission as never, "bootstrap", 0);
  const job = context.jobs.create(actor, { id: "job", title: "Job", description: "Fixture", owner: "owner", project: actor.project });
  const moved = context.jobs.bulkTransition(actor, {
    changes: [{ id: job.id, transition: { stage: "active", expectedRevision: job.revision, reason: "start" } }],
  });
  expect(moved.map(item => item.stage)).toEqual(["active"]);
  expect(() => context.jobs.bulkTransition(actor, {
    changes: [{ id: job.id, transition: { stage: "queued", expectedRevision: moved[0]!.revision, reason: "back" } }],
  })).toThrow();
}, 30000);
