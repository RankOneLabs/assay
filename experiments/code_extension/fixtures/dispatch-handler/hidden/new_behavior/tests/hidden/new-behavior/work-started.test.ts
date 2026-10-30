import { expect, test } from "bun:test";
import * as events from "../../../src/domain/run-event";
import type { RunEventRow } from "../../../src/domain/run-event";

const row = (overrides: Partial<RunEventRow> = {}): RunEventRow => ({
  sequence: "73", operation: "work_started", run_id: "run-1", run_unit_id: "unit-1",
  stage_instance_id: null, stage_key: null, unit_id: null, work_order_id: "order-1",
  wait_id: null, output_name: null, collection_key: null, artifact_revision_id: null,
  attention: null, continuation: null, detail: { source: "queue" },
  created_at: "2026-09-26T12:00:00.000Z", ...overrides,
});

test("work-started direct handler preserves payload", () => {
  const handler = (events as unknown as Record<string, (value: RunEventRow) => unknown>)["projectWorkStartedEvent"];
  expect(typeof handler).toBe("function");
  if (!handler) return;
  expect(handler(row())).toEqual({sequence: "73", occurred_at: "2026-09-26T12:00:00.000Z",
    operation: "work_started", payload: {run_id: "run-1", run_unit_id: "unit-1", stage_instance_id: null,
    stage_key: null, unit_id: null, work_order_id: "order-1", wait_id: null, output_name: null,
    collection_key: null, artifact_revision_id: null, attention: null, continuation: null, detail: {source: "queue"}}});
});

test("work-started is validated through dispatch", () => {
  expect(String(events.projectRunEvent(row()).payload.work_order_id)).toBe("order-1");
  expect(() => events.projectRunEvent(row({work_order_id: null}))).toThrow("73");
  expect(() => events.projectRunEvent(row({run_unit_id: null}))).toThrow("work_started");
});

test("work-started direct handler rejects invalid identities", () => {
  const handler = (events as unknown as Record<string, (value: RunEventRow) => unknown>)["projectWorkStartedEvent"];
  expect(typeof handler).toBe("function");
  if (!handler) return;
  expect(() => handler(row({work_order_id: null}))).toThrow();
  expect(() => handler(row({run_unit_id: null}))).toThrow();
});
