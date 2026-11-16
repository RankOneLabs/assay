import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { peerGuard } from "../../../evidence_kind/sibling.ts";

test("fact:evidence_kind_rename_sibling_only: sibling_only behavior", () => {
  expect(peerGuard("attestation")).toBe(true);
  expect(peerGuard("document")).toBe(false);
}, 30000);
