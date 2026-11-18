import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { validateRegisteredValue } from "../../../src/validation/registered_evidence_kinds.ts";

test("fact:evidence_kind_additive_name_only: name_only behavior", () => {
  expect(validateRegisteredValue("attestation")).toBe(true);
}, 30000);
