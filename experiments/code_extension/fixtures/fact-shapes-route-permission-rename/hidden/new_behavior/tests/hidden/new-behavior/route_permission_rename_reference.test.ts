import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { edit } from "../../../route_permission/edit.ts";

test("fact:route_permission_rename_reference: reference behavior", () => {
  expect(edit("record", "case_inspect" as never).value).toBe("case_inspect");
  expect(() => edit("record", "case_read" as never)).toThrow();
}, 30000);
