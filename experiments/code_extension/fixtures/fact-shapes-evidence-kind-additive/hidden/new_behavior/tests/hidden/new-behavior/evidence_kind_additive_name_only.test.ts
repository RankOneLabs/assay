import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { supportsFeature } from "../../../evidence_kind/names.ts";

test("fact:evidence_kind_additive_name_only: name_only behavior", () => {
  expect(supportsFeature("attestation")).toBe(true);
});
