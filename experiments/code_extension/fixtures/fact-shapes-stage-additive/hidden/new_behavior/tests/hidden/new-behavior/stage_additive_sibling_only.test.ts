import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { acceptsPeerStage as peerGuard } from "../../../src/services/peer.ts";

test("fact:stage_additive_sibling_only: sibling_only behavior", () => {
  expect(peerGuard("triaged")).toBe(true);
}, 30000);
