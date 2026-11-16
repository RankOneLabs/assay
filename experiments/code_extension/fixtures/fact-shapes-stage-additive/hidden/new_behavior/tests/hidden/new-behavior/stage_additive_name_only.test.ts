import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { validateRegisteredValue } from "../../../stage/names.ts";

test("fact:stage_additive_name_only: name_only behavior", () => {
  expect(validateRegisteredValue("triaged")).toBe(true);
}, 30000);
