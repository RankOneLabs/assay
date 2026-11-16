import { expect, test } from "bun:test";
import { validateKey } from "../../../stage/anchor.ts";

test("fact:stage_rename_anchor: anchor behavior", () => {
  expect(validateKey("a_1-B")).toBe("a_1-B");
  expect(validateKey("a".repeat(80))).toHaveLength(80);
  for (const label of ["", "bad/label", "a".repeat(81)]) expect(() => validateKey(label)).toThrow();
});
