import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { ServiceContext } from "../../../src/context.ts";

test("fact:stage_rename_name_only: name_only behavior", () => {
  using context = new ServiceContext();
  const actor = { id: "admin", project: "project" };
  for (const permission of ["case_read", "case_write", "case_admin"]) context.grantRepository.grant(actor, permission as never, "bootstrap", 0);
  const rule = context.escalations.createRule(actor, { id: "waiting-sla", stage: "triaged", maxAgeMinutes: 60, target: actor.id });
  expect(rule.stage).toBe("triaged" as never);
  expect(() => context.escalations.createRule(actor, { id: "former", stage: "queued", maxAgeMinutes: 60, target: actor.id })).toThrow();
}, 30000);
