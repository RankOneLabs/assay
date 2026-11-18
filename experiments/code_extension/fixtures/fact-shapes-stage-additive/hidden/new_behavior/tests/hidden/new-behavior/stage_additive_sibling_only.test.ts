import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { peerGuard } from "../../../src/services/stage_peer.ts";

test("fact:stage_additive_sibling_only: sibling_only behavior", () => {
  expect(peerGuard("triaged")).toBe(true);
}, 30000);
