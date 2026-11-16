import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { supportsFeature } from "../../../stage/sibling.ts";

test("fact:stage_additive_sibling_only: sibling_only behavior", () => {
  expect(supportsFeature("triaged")).toBe(true);
});
