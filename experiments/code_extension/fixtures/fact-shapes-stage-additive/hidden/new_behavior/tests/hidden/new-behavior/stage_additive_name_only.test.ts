import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { ServiceContext } from "../../../src/context.ts";

test("fact:stage_additive_name_only: name_only behavior", () => {
  using context = new ServiceContext();
  const actor = { id: "admin", project: "project" };
  for (const permission of ["case_read", "case_write", "case_admin"]) context.grantRepository.grant(actor, permission as never, "bootstrap", 0);
  const rule = context.escalations.createRule(actor, {
    id: "triage-sla", stage: "triaged", maxAgeMinutes: 60, target: actor.id,
  });
  expect(rule.stage).toBe("triaged" as never);
}, 30000);
