import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { edit } from "../../../stage/edit.ts";
test("existing feature operations retain validation", () => {
  expect(edit("record", "active" as never).value).toBe("active");
  expect(() => edit("bad/label", "active" as never)).toThrow();
  expect(() => edit("record", "active" as never, -1)).toThrow();
});
