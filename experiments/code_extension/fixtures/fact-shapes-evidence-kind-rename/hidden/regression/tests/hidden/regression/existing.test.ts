import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { edit } from "../../../evidence_kind/edit.ts";
test("existing feature operations retain validation", () => {
  expect(edit("record", "image" as never).value).toBe("image");
  expect(() => edit("bad/label", "image" as never)).toThrow();
  expect(() => edit("record", "image" as never, -1)).toThrow();
});
