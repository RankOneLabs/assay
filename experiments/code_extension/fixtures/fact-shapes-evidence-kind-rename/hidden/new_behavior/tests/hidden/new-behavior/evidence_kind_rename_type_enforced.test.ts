import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { supportsFeature } from "../../../evidence_kind/types.ts";

test("fact:evidence_kind_rename_type_enforced: type_enforced behavior", () => {
  expect(supportsFeature("attestation")).toBe(true);
  expect(supportsFeature("document")).toBe(false);
});
