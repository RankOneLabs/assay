import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { edit } from "../../../evidence_kind/edit.ts";

test("fact:evidence_kind_additive_reference: reference behavior", () => {
  expect(edit("record", "attestation" as never).value).toBe("attestation");
}, 30000);
