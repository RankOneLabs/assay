import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { peerGuard } from "../../../src/services/route_permission_peer.ts";

test("fact:route_permission_rename_sibling_only: sibling_only behavior", () => {
  expect(peerGuard("case_inspect")).toBe(true);
  expect(peerGuard("case_read")).toBe(false);
}, 30000);
