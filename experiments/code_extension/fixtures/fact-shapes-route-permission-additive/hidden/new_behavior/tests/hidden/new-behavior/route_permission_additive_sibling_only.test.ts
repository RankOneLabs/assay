import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { acceptsPeerPermission as peerGuard } from "../../../src/services/peer.ts";

test("fact:route_permission_additive_sibling_only: sibling_only behavior", () => {
  expect(peerGuard("case_inspect")).toBe(true);
}, 30000);
