import { expect, test } from "bun:test";
import { projectRunEvent, type RunEventRow } from "../../../../src/domain/run-event";

const base = {
  sequence: "5",
  run_id: "11111111-1111-4111-8111-111111111111",
  run_unit_id: "22222222-2222-4222-8222-222222222222",
  stage_instance_id: "33333333-3333-4333-8333-333333333333",
  stage_key: "build",
  unit_id: "unit-1",
  work_order_id: null,
  wait_id: null,
  output_name: "report",
  collection_key: null,
  artifact_revision_id: "44444444-4444-4444-8444-444444444444",
  attention: null,
  continuation: null,
  detail: {},
  created_at: "2026-02-02T00:00:00.000Z",
};

test("an opened gate still exposes its stronger ledger invariants", () => {
  const event = projectRunEvent({
    ...base,
    operation: "gate_opened",
    wait_id: "55555555-5555-4555-8555-555555555555",
    attention: "required",
    continuation: "waiting",
  } as unknown as RunEventRow);
  if (event.operation !== "gate_opened") throw new Error("expected a gate_opened event");
  expect(String(event.payload.wait_id)).toBe("55555555-5555-4555-8555-555555555555");
  expect(event.payload.attention).toBe("required");
});

test("an incomplete gate is still refused by sequence and operation", () => {
  expect(() =>
    projectRunEvent({ ...base, operation: "gate_opened", wait_id: null } as unknown as RunEventRow),
  ).toThrow("run event '5' has an invalid gate_opened payload");
});

test("an observed pull request still exposes its typed detail", () => {
  const event = projectRunEvent({
    ...base,
    operation: "pull_request_observed",
    detail: {
      repository_key: "assay",
      pull_request_url: "https://example.invalid/pr/1",
      state: "open",
      source: "cohort",
      merged_at: null,
    },
  } as unknown as RunEventRow);
  if (event.operation !== "pull_request_observed") {
    throw new Error("expected a pull_request_observed event");
  }
  expect(event.payload.detail.repository_key).toBe("assay");
  expect(event.payload.detail.merged_at).toBeNull();
});

test("a pull request missing its state is still refused", () => {
  expect(() =>
    projectRunEvent({
      ...base,
      operation: "pull_request_observed",
      detail: {
        repository_key: "assay",
        pull_request_url: "https://example.invalid/pr/1",
        source: "cohort",
        merged_at: null,
      },
    } as unknown as RunEventRow),
  ).toThrow("run event '5' has an invalid pull_request_observed payload");
});

test("an operation without stronger invariants still passes through unvalidated", () => {
  const event = projectRunEvent({
    ...base,
    operation: "unit_admitted",
    run_unit_id: null,
  } as unknown as RunEventRow);
  expect(event.operation).toBe("unit_admitted");
  expect(event.payload.run_unit_id).toBeNull();
});
