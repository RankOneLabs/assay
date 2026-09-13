import { expect, test } from "bun:test";
import { gridState, orderedCategories } from "../../src/app";
import type { CellSummary } from "../../src/types";

function cell(update: Partial<CellSummary>): CellSummary {
  return {
    cell_id: "c", subject_id: "s", arm_id: "a", worker_repeat: 0, status: "succeeded",
    error_type: null, error_message: null, record_refs: [], exclusion: null, verdicts: [], issues: [], ...update,
  };
}

test("grid labels missing, failed, ambiguous, and negative distinctly", () => {
  expect(gridState(cell({ status: "missing" }))).toBe("missing");
  expect(gridState(cell({ status: "failed" }))).toBe("failed");
  expect(gridState(cell({ verdicts: [{ evaluator_id: "e", values: [null], repeat_statuses: ["failed"], failures: ["AmbiguousStructure: unclear"], agreed: null, categories: null }] }))).toBe("ambiguous");
  expect(gridState(cell({ verdicts: [{ evaluator_id: "e", values: ["incorrect"], repeat_statuses: ["succeeded"], failures: [], agreed: true, categories: ["incorrect", "correct"] }] }))).toBe("negative");
});

test("ordinal values follow each evaluator's declared order", () => {
  const abstraction = orderedCategories(["duplicated", "mixed", "reused"], { reused: 8, duplicated: 1, mixed: 3 });
  const correctness = orderedCategories(["incorrect", "correct"], { correct: 9, incorrect: 2 });
  expect(abstraction.map(([name]) => name)).toEqual(["duplicated", "mixed", "reused"]);
  expect(correctness.map(([name]) => name)).toEqual(["incorrect", "correct"]);
});
