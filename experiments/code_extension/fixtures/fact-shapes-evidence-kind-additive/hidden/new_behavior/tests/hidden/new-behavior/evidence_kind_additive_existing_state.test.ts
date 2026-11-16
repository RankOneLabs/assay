import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { ServiceContext } from "../../../src/context.ts";

test("fact:evidence_kind_additive_existing_state: existing_state behavior", () => {
  using context = new ServiceContext();
  const actor = { id: "admin", project: "project" };
  for (const permission of ["case_write", "case_admin", "case_read"]) context.grantRepository.grant(actor, permission as never, "bootstrap", 0);
  const job = context.jobs.create(actor, { id: "job", title: "Job", description: "Fixture", owner: "owner", project: actor.project });
  context.evidence.setDefaultKind(actor, "image");
  context.evidence.setDefaultKind(actor, "attestation");
  expect(context.evidence.attach(actor, job.id, { id: "first", title: "First", content: "First", author: "author" }).kind).toBe("attestation");
  context.evidence.clearDefaultKind(actor);
  expect(() => context.evidence.attach(actor, job.id, { id: "second", title: "Second", content: "Second", author: "author" })).toThrow();
}, 30000);
