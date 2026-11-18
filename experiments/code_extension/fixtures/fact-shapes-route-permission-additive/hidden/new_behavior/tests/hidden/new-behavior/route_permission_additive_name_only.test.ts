import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { validateRegisteredValue } from "../../../src/validation/registered_route_permissions.ts";

test("fact:route_permission_additive_name_only: name_only behavior", () => {
  expect(validateRegisteredValue("case_inspect")).toBe(true);
}, 30000);
