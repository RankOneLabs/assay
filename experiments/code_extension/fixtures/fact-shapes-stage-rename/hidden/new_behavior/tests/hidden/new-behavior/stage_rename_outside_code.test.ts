import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { ServiceContext } from "../../../src/context.ts";

test("fact:stage_rename_outside_code: outside_code behavior", () => {
  using context = new ServiceContext();
  const actor = { id: "admin", project: "project" };
  for (const permission of ["case_write", "case_admin", "case_read"]) context.grantRepository.grant(actor, permission as never, "bootstrap", 0);
  const job = context.jobs.create(actor, { id: "job", title: "Job", description: "Fixture", owner: "owner", project: actor.project });
  expect(job.stage).toBe("triaged");
  expect(context.jobs.get(actor, job.id).stage).toBe("triaged");
}, 30000);
