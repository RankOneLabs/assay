import { expect, test } from "bun:test";
import { StoredRoutePermission } from "../../../route_permission/state.ts";

test("fact:route_permission_rename_existing_state: existing_state behavior", () => {
  const source = new StoredRoutePermission();
  source.set("record", "case_inspect" as never);
  expect(source.supportsFeature("case_inspect", "record")).toBe(true);
  source.remove("record");
  expect(source.supportsFeature("case_inspect", "record")).toBe(false);
  source.set("old-record", "case_read" as never);
  expect(source.supportsFeature("case_read", "old-record")).toBe(false);
});
