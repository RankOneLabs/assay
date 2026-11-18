import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { validateRegisteredValue } from "../../../src/validation/registered_stages.ts";

test("fact:stage_rename_name_only: name_only behavior", () => {
  expect(validateRegisteredValue("triaged")).toBe(true);
  expect(validateRegisteredValue("queued")).toBe(false);
}, 30000);
