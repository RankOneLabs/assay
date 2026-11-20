import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { ServiceContext } from "../../../src/context.ts";

test("fact:stage_additive_outside_code: outside_code behavior", () => {
  using context = new ServiceContext();
  const actor = { id: "admin", project: "project" };
  for (const permission of ["case_read", "case_write", "case_admin"]) context.grantRepository.grant(actor, permission as never, "bootstrap", 0);
  context.maintenance.setRetention(actor, { stage: "triaged", days: 30 });
  expect(context.maintenance.retention(actor)).toContainEqual({ stage: "triaged", days: 30 });
  expect(() => context.maintenance.setRetention(actor, { stage: "triaged", days: 31 })).toThrow();
  expect(context.maintenance.retention(actor)).toContainEqual({ stage: "triaged", days: 30 });
}, 30000);
