import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { acceptsPeerKind as peerGuard } from "../../../src/services/peer.ts";

test("fact:evidence_kind_additive_sibling_only: sibling_only behavior", () => {
  expect(peerGuard("attestation")).toBe(true);
}, 30000);
