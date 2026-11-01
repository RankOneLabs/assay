import { expect, test } from "bun:test";
import { projectRunEvent, type RunEventRow } from "../../../src/domain/run-event";

const row = (overrides: Partial<RunEventRow> = {}): RunEventRow => ({
  sequence: "41",
  operation: "slot_invalidated",
  run_id: "11111111-1111-4111-8111-111111111111",
  run_unit_id: "22222222-2222-4222-8222-222222222222",
  stage_instance_id: "33333333-3333-4333-8333-333333333333",
  stage_key: "build",
  unit_id: "unit-1",
  work_order_id: null,
  wait_id: null,
  output_name: "report",
  collection_key: null,
  artifact_revision_id: null,
  attention: null,
  continuation: null,
  detail: { invalidation_kind: "input_revised" },
  superseded_by: "44444444-4444-4444-8444-444444444444",
  created_at: "2026-02-02T00:00:00.000Z",
  ...overrides,
});

test("an invalidated slot projects its own operation and keeps the row's envelope", () => {
  const event = projectRunEvent(row());
  expect(event.operation).toBe("slot_invalidated");
  expect(event.sequence).toBe("41");
  expect(event.occurred_at).toBe("2026-02-02T00:00:00.000Z");
});

test("the projected payload narrows the slot's required fields", () => {
  const event = projectRunEvent(row());
  if (event.operation !== "slot_invalidated") throw new Error("expected a slot_invalidated event");
  expect(String(event.payload.run_unit_id)).toBe("22222222-2222-4222-8222-222222222222");
  expect(event.payload.output_name).toBe("report");
  expect(event.payload.detail.invalidation_kind).toBe("input_revised");
});

test("the superseding revision reaches the consumer through the payload", () => {
  const event = projectRunEvent(row());
  if (event.operation !== "slot_invalidated") throw new Error("expected a slot_invalidated event");
  expect(event.payload.superseded_by as string | null).toBe("44444444-4444-4444-8444-444444444444");
});

test("a slot that nothing superseded is still projected", () => {
  const event = projectRunEvent(row({ superseded_by: null }));
  if (event.operation !== "slot_invalidated") throw new Error("expected a slot_invalidated event");
  expect(event.payload.superseded_by).toBeNull();
});

test("an invalidated slot without its run unit is refused by sequence and operation", () => {
  expect(() => projectRunEvent(row({ run_unit_id: null }))).toThrow(
    "run event '41' has an invalid slot_invalidated payload",
  );
});

test("an invalidated slot without an output name is refused", () => {
  expect(() => projectRunEvent(row({ output_name: null }))).toThrow(
    "run event '41' has an invalid slot_invalidated payload",
  );
});

test("an invalidated slot without an invalidation kind is refused", () => {
  expect(() => projectRunEvent(row({ detail: { note: "no kind" } }))).toThrow(
    "run event '41' has an invalid slot_invalidated payload",
  );
});
