import { expect, test } from "bun:test";
import { StoredEvidenceKind } from "../../../evidence_kind/state.ts";

test("fact:evidence_kind_additive_existing_state: existing_state behavior", () => {
  const source = new StoredEvidenceKind();
  source.set("record", "attestation" as never);
  expect(source.supportsFeature("attestation", "record")).toBe(true);
  source.remove("record");
  expect(source.supportsFeature("attestation", "record")).toBe(false);
});
