import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { validateRegisteredValue } from "../../../src/validation/registered_route_permissions.ts";

test("fact:route_permission_rename_name_only: name_only behavior", () => {
  expect(validateRegisteredValue("case_inspect")).toBe(true);
  expect(validateRegisteredValue("case_read")).toBe(false);
}, 30000);
