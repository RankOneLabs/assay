import { expect, test } from "bun:test";
import { StoredRoutePermission } from "../../../route_permission/state.ts";

test("fact:route_permission_additive_existing_state: existing_state behavior", () => {
  const source = new StoredRoutePermission();
  source.set("record", "case_inspect" as never);
  expect(source.supportsFeature("case_inspect", "record")).toBe(true);
  source.remove("record");
  expect(source.supportsFeature("case_inspect", "record")).toBe(false);
});
