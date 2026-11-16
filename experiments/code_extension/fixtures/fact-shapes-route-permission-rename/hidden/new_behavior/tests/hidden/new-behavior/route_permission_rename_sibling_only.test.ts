import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { peerGuard } from "../../../route_permission/sibling.ts";

test("fact:route_permission_rename_sibling_only: sibling_only behavior", () => {
  expect(peerGuard("case_inspect")).toBe(true);
  expect(peerGuard("case_read")).toBe(false);
}, 30000);
