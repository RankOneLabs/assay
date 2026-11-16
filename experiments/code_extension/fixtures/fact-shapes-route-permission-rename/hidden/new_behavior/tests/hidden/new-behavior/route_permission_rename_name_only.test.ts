import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { supportsFeature } from "../../../route_permission/names.ts";

test("fact:route_permission_rename_name_only: name_only behavior", () => {
  expect(supportsFeature("case_inspect")).toBe(true);
  expect(supportsFeature("case_read")).toBe(false);
});
