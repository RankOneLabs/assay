import { expect, test } from "bun:test";
import { SessionService } from "../../../stage/state.ts";

test("fact:stage_rename_existing_state: existing_state behavior", () => {
  const source = new SessionService();
  source.startBuild("record");
  expect(source.supportsFeature("triaged", "record")).toBe(true);
  source.endSession("record");
  expect(source.supportsFeature("triaged", "record")).toBe(false);
  source.startBuild("old-record");
  expect(source.supportsFeature("queued", "old-record")).toBe(false);
});
