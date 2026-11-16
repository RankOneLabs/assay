import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { requestFeature as edit } from "../../../route_permission/edit.ts";

test("fact:route_permission_additive_reference: reference behavior", () => {
  expect(edit("record", "case_inspect" as never).value).toBe("case_inspect");
  expect(() => edit("record", "case_inspect" as never, -1)).toThrow();
});
