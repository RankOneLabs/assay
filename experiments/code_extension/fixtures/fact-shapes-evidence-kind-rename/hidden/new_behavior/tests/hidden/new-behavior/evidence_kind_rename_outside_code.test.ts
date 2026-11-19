import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { ServiceContext } from "../../../src/context.ts";

test("fact:evidence_kind_rename_outside_code: outside_code behavior", () => {
  using context = new ServiceContext();
  const actor = { id: "admin", project: "project" };
  for (const permission of ["case_write", "case_admin", "case_read"]) context.grantRepository.grant(actor, permission as never, "bootstrap", 0);
  const job = context.jobs.create(actor, { id: "job", title: "Job", description: "Fixture", owner: "owner", project: actor.project });
  context.evidence.attach(actor, job.id, { id: "proof", kind: "attestation", title: "Proof", content: "Stored proof", author: "author" });
  expect(context.evidence.get(actor, job.id, "proof").kind).toBe("attestation");
}, 30000);
