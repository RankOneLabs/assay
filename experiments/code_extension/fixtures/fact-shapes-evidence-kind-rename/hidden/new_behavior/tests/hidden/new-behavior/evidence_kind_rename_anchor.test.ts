import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { edit } from "../../../evidence_kind/edit.ts";

test("fact:evidence_kind_rename_anchor: anchor behavior", () => {
  expect(edit("a".repeat(80), "image" as never).key).toHaveLength(80);
  expect(edit("a_1-B", "image" as never).key).toBe("a_1-B");
  for (const label of ["", "bad/label", "a".repeat(81)]) expect(() => edit(label, "image" as never)).toThrow();
}, 30000);
