import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { ServiceContext } from "../../../src/context.ts";

test("fact:route_permission_additive_existing_state: existing_state behavior", () => {
  using context = new ServiceContext();
  const actor = { id: "admin", project: "project" };
  for (const permission of ["case_write", "case_admin", "case_read"]) context.grantRepository.grant(actor, permission as never, "bootstrap", 0);
  context.access.setDefaultPermission(actor, "case_write");
  context.access.setDefaultPermission(actor, "case_inspect");
  expect(context.access.grantDefault(actor, "first").permission).toBe("case_inspect");
  context.access.clearDefaultPermission(actor);
  expect(() => context.access.grantDefault(actor, "second")).toThrow();
}, 30000);
