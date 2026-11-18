import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { edit } from "../../../route_permission/edit.ts";

test("fact:route_permission_rename_anchor: anchor behavior", () => {
  expect(edit("a".repeat(80), "case_write" as never).key).toHaveLength(80);
  expect(edit("a_1-B", "case_write" as never).key).toBe("a_1-B");
  for (const label of ["", "bad/label", "a".repeat(81)]) expect(() => edit(label, "case_write" as never)).toThrow();
}, 30000);
