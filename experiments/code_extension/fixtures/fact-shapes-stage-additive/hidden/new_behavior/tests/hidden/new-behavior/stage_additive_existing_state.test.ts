import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { ServiceContext } from "../../../src/context.ts";

test("fact:stage_additive_existing_state: existing_state behavior", () => {
  using context = new ServiceContext();
  const actor = { id: "admin", project: "project" };
  for (const permission of ["case_read", "case_write", "case_admin"]) context.grantRepository.grant(actor, permission as never, "bootstrap", 0);
  // A stored job in the new stage, as an import leaves it.
  const triaged = (id: string) => context.jobRepository.create(
    { id, title: id, description: "Fixture", owner: "owner", project: actor.project, priority: 0 } as never,
    "triaged" as never, 1,
  );
  const job = triaged("job");
  expect(context.exports.bundle(actor, job.id).job.owner).toBe("owner");
  context.jobs.patch(actor, job.id, { owner: "triager", priority: 5, expectedRevision: job.revision });
  expect(context.exports.bundle(actor, job.id).job).toMatchObject({ owner: "triager", priority: 5 });
}, 30000);
