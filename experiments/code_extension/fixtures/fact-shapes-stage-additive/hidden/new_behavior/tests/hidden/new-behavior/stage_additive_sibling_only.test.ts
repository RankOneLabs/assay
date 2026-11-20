import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { ServiceContext } from "../../../src/context.ts";

test("fact:stage_additive_sibling_only: sibling_only behavior", () => {
  using context = new ServiceContext();
  const actor = { id: "admin", project: "project" };
  for (const permission of ["case_read", "case_write", "case_admin"]) context.grantRepository.grant(actor, permission as never, "bootstrap", 0);
  // A stored job in the new stage, as an import leaves it.
  const triaged = (id: string) => context.jobRepository.create(
    { id, title: id, description: "Fixture", owner: "owner", project: actor.project, priority: 0 } as never,
    "triaged" as never, 1,
  );
  const jobs = [triaged("first"), triaged("second")];
  const moved = context.jobs.bulkTransition(actor, {
    changes: jobs.map(job => ({ id: job.id, transition: { stage: "queued", expectedRevision: job.revision, reason: "triaged" } })),
  });
  expect(moved.map(job => job.stage)).toEqual(["queued", "queued"]);
}, 30000);
