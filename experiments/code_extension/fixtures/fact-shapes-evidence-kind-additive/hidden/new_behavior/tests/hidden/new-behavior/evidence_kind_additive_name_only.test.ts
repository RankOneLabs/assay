import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { validateRegisteredKind as validateRegisteredValue } from "../../../src/validation/registry.ts";

test("fact:evidence_kind_additive_name_only: name_only behavior", () => {
  expect(validateRegisteredValue("attestation")).toBe(true);
}, 30000);
