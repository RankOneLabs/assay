import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { supportsFeature } from "../../../stage/names.ts";

test("fact:stage_additive_name_only: name_only behavior", () => {
  expect(supportsFeature("triaged")).toBe(true);
});
