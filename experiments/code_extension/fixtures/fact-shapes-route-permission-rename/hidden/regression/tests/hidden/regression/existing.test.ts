import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { edit } from "../../../route_permission/edit.ts";
test("existing feature operations retain validation", () => {
  expect(edit("record", "case_write" as never).value).toBe("case_write");
  expect(() => edit("bad/label", "case_write" as never)).toThrow();
  expect(() => edit("record", "case_write" as never, -1)).toThrow();
});
