import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { validateRegisteredStage as validateRegisteredValue } from "../../../src/validation/registry.ts";

test("fact:stage_additive_name_only: name_only behavior", () => {
  expect(validateRegisteredValue("triaged")).toBe(true);
}, 30000);
