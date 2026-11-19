import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { ServiceContext } from "../../../src/context.ts";

test("fact:route_permission_additive_outside_code: outside_code behavior", () => {
  using context = new ServiceContext();
  const actor = { id: "admin", project: "project" };
  for (const permission of ["case_write", "case_admin"]) context.grantRepository.grant(actor, permission as never, "bootstrap", 0);
  context.access.grant(actor, "inspector", "case_inspect");
  expect(context.access.list(actor, "inspector").map(grant => grant.permission)).toEqual(["case_inspect"]);
}, 30000);
