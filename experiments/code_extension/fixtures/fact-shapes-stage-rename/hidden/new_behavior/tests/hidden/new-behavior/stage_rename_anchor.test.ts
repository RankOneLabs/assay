import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { edit } from "../../../stage/edit.ts";

test("fact:stage_rename_anchor: anchor behavior", () => {
  expect(edit("a".repeat(80), "active" as never).key).toHaveLength(80);
  expect(edit("a_1-B", "active" as never).key).toBe("a_1-B");
  for (const label of ["", "bad/label", "a".repeat(81)]) expect(() => edit(label, "active" as never)).toThrow();
}, 30000);
