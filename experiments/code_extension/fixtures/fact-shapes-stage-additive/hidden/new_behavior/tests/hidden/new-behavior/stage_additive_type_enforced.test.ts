import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { supportsFeature } from "../../../stage/types.ts";

test("fact:stage_additive_type_enforced: type_enforced behavior", () => {
  expect(supportsFeature("triaged")).toBe(true);
});
