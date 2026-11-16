import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { supportsFeature } from "../../../route_permission/types.ts";

test("fact:route_permission_rename_type_enforced: type_enforced behavior", () => {
  expect(supportsFeature("case_inspect")).toBe(true);
  expect(supportsFeature("case_read")).toBe(false);
});
