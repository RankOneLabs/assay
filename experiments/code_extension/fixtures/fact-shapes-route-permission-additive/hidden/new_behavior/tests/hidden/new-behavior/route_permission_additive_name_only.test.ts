import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { validateRegisteredValue } from "../../../route_permission/names.ts";

test("fact:route_permission_additive_name_only: name_only behavior", () => {
  expect(validateRegisteredValue("case_inspect")).toBe(true);
}, 30000);
