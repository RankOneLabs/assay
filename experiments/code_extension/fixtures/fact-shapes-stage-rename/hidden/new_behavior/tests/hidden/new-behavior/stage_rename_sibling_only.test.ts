import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { peerGuard } from "../../../src/services/stage_peer.ts";

test("fact:stage_rename_sibling_only: sibling_only behavior", () => {
  expect(peerGuard("triaged")).toBe(true);
  expect(peerGuard("queued")).toBe(false);
}, 30000);
