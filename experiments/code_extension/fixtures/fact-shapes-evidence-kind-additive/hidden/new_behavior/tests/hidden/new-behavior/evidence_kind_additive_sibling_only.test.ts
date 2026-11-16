import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { supportsFeature } from "../../../evidence_kind/sibling.ts";

test("fact:evidence_kind_additive_sibling_only: sibling_only behavior", () => {
  expect(supportsFeature("attestation")).toBe(true);
});
