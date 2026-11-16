import { expect, test } from "bun:test";
import { StoredEvidenceKind } from "../../../evidence_kind/state.ts";

test("fact:evidence_kind_rename_existing_state: existing_state behavior", () => {
  const source = new StoredEvidenceKind();
  source.set("record", "attestation" as never);
  expect(source.supportsFeature("attestation", "record")).toBe(true);
  source.remove("record");
  expect(source.supportsFeature("attestation", "record")).toBe(false);
  source.set("old-record", "document" as never);
  expect(source.supportsFeature("document", "old-record")).toBe(false);
});
