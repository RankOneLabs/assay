import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { validateRegisteredKind as validateRegisteredValue } from "../../../src/validation/registry.ts";

test("fact:evidence_kind_rename_name_only: name_only behavior", () => {
  expect(validateRegisteredValue("attestation")).toBe(true);
  expect(validateRegisteredValue("document")).toBe(false);
}, 30000);
