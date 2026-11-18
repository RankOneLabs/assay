import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { edit } from "../../../stage/edit.ts";

test("fact:stage_additive_reference: reference behavior", () => {
  expect(edit("record", "triaged" as never).value).toBe("triaged");
}, 30000);
