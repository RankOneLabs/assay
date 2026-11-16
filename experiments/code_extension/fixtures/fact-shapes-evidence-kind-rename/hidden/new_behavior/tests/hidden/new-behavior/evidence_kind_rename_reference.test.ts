import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { requestFeature as edit } from "../../../evidence_kind/edit.ts";

test("fact:evidence_kind_rename_reference: reference behavior", () => {
  expect(edit("record", "attestation" as never).value).toBe("attestation");
  expect(() => edit("record", "attestation" as never, -1)).toThrow();
  expect(() => edit("record", "document" as never)).toThrow();
});
