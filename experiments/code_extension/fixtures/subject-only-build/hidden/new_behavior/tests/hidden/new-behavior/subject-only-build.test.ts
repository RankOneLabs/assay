import { expect, test } from "bun:test";
import type { ItemOccurrenceId, QuestionId } from "../../../src/domain/identity";
import type { JsonValue } from "../../../src/domain/primitives";
import { oakridgeQuestions, PILOT_QUESTION_IDS, type PilotExpectations, type PilotQuestion } from "../../../src/grading/catalogue/oakridge-questions";
import type { CapturedRevision } from "../../../src/grading/evidence-packages/capture";
import { pinnedInputRecipe, pinnedPilotRecipe, type PilotEvidenceRecipe } from "../../../src/grading/evidence-packages/pilot-recipe";
import { runPackages } from "../../../src/producers/oakridge/evidence-packages";
import { oakridgeDevelopmentCatalogue } from "../../../src/projection/catalogue/oakridge-development";
import { selectRevision } from "../../../src/projection/extractor";

// Inlined rather than imported from the pinned grading fixture, which opens Postgres.
const expectation = { definition_id: "definition-1", artifact_schema_version: "1" };
const expectations = Object.fromEntries(PILOT_QUESTION_IDS.map((id) => [id, expectation])) as PilotExpectations;
const QUESTIONS = oakridgeQuestions(expectations);
const ID = "plan.criterion_standalone";

function captured(revision_id: string, unit_id: string, body: JsonValue, at: string,
  provenance: { definition_id: string | null; artifact_schema_version: string | null } = expectation): CapturedRevision {
  const pass = selectRevision(body, revision_id, oakridgeDevelopmentCatalogue("plan", "development-v1"));
  return { ...provenance, revision_id, unit_id, artifact_kind: "plan", recorded_at: new Date(at),
    items: pass.items.map(({ item }, index) => ({ ...item, revision_id, occurrence_id: `${revision_id}-${index}` as ItemOccurrenceId })) };
}

/** A plan whose first criterion cites nothing and whose second cites a decision. */
function plan(revision_id: string, unit_id = "plan/alpha", provenance = expectation): CapturedRevision {
  return captured(revision_id, unit_id, { cohorts: [{ id: "alpha", decisions: [{ id: "decision-a", text: "Choose A" }],
    acceptance_criteria: [{ id: "crit-a", text: "A works", task_ids: [], decision_ids: [] },
      { id: "crit-b", text: "A fails closed", task_ids: [], decision_ids: ["decision-a"] }] }] },
  "2026-11-01T00:00:00Z", provenance);
}

const subjectSlot = (role: string) => ({ role, source: { from: "subject" }, min_count: 1, max_count: 1 });
function recipe(overrides: Record<string, unknown> = {}): PilotEvidenceRecipe {
  return { recipe_version: "v1", subject: { artifact_kind: "plan", item_kind: "criterion" }, build: { kind: "subject_only" },
    input: [], output: [subjectSlot("plan_criterion")], ...overrides } as unknown as PilotEvidenceRecipe;
}
function question(pin: PilotEvidenceRecipe = recipe()): PilotQuestion {
  const definition = { ...QUESTIONS["plan.criterion_traceability"].definition, question_id: ID as QuestionId,
    input_recipe: pinnedInputRecipe(pin) };
  return { definition, text: "Is this plan criterion actionable on its own?" };
}

function derive(revisions: readonly CapturedRevision[], extra: Record<string, PilotQuestion> = {}) {
  const result = runPackages(revisions, { [ID]: question(), ...extra });
  if (!result.ok) throw new Error(result.error.detail);
  return result.value;
}
const criterion = (revision: CapturedRevision, local_id: string) =>
  revision.items.find((item) => item.item_kind === "criterion" && item.producer_local_id === local_id)!;

test("reachability: a subject_only pin is read as a supported slot recipe", () => {
  expect(pinnedPilotRecipe(question().definition)?.build as unknown).toEqual({ kind: "subject_only" });
});

test("reachability: a criterion that cites nothing is packaged on its own and eligible", () => {
  const revision = plan("plan-1");
  const derived = derive([revision]);
  const subject = criterion(revision, "crit-a");
  const pack = derived.packages.find((item) => item.question_id === ID && item.subject.occurrence_id === subject.occurrence_id);
  expect(pack?.evidence.references.map((ref) => ref.ref)).toEqual(["plan_criterion:crit-a"]);
  expect(derived.eligibility.find((item) => item.question_id === ID && item.occurrence_id === subject.occurrence_id)?.decision)
    .toEqual({ tag: "eligible", payload: { evidence_set_id: pack!.evidence.evidence_set_id } });
});

test("semantics: every subject item is packaged alone, whatever it links, and nothing else is", () => {
  const revision = plan("plan-1");
  const derived = derive([revision]);
  expect(derived.packages.map((item) => [item.question_id, item.subject.occurrence_id, item.revision_id,
    item.evidence.references.map((ref) => ref.ref)])).toEqual([
    [ID, criterion(revision, "crit-a").occurrence_id, "plan-1", ["plan_criterion:crit-a"]],
    [ID, criterion(revision, "crit-b").occurrence_id, "plan-1", ["plan_criterion:crit-b"]]]);
  expect(derived.exclusions).toEqual([]);
  expect(derived.eligibility.map((item) => item.decision.tag)).toEqual(["eligible", "eligible"]);
});

test("semantics: a package holds only the subject's captured reference and is complete", () => {
  const revision = plan("plan-1");
  const subject = criterion(revision, "crit-b");
  const pack = derive([revision]).packages.find((item) => item.subject.occurrence_id === subject.occurrence_id)!;
  expect(pack.evidence.references).toMatchObject([{ ref: "plan_criterion:crit-b", kind: "internal",
    content: subject.selected_value, deep_link: `oakridge://revision/plan-1#${subject.path}` }]);
  expect([pack.evidence.is_incomplete, pack.evidence.incompleteness_reason]).toEqual([false, null]);
});

test("semantics: a revision with unsupported provenance keeps its inapplicable decisions and gets no package", () => {
  const supported = plan("plan-1");
  const unsupported = plan("plan-2", "plan/beta", { definition_id: "definition-other", artifact_schema_version: "1" });
  const derived = derive([supported, unsupported]);
  expect(derived.packages.map((item) => item.revision_id)).toEqual(["plan-1", "plan-1"]);
  const decisions = derived.eligibility.filter((item) => item.occurrence_id.startsWith("plan-2"));
  expect(decisions.map((item) => [item.occurrence_id, item.decision.tag])).toEqual([
    [criterion(unsupported, "crit-a").occurrence_id, "inapplicable"], [criterion(unsupported, "crit-b").occurrence_id, "inapplicable"]]);
});

test("semantics: a subject_only pin naming a linked or unscheduled slot is not readable", () => {
  const linked = recipe({ input: [{ role: "plan_decision", min_count: 0, max_count: 20,
    source: { from: "linked", link_type: "derived_from", direction: "out", artifact_kind: "plan", item_kind: "decision" } }] });
  const unscheduled = recipe({ input: [{ role: "plan_task", min_count: 1, max_count: 1, source: { from: "unscheduled" } }] });
  expect([pinnedPilotRecipe(question(linked).definition), pinnedPilotRecipe(question(unscheduled).definition)]).toEqual([null, null]);
  expect(runPackages([plan("plan-1")], { [ID]: question(linked) }))
    .toMatchObject({ ok: false, error: { detail: "question has no supported captured evidence recipe" } });
});

test("semantics: a linked_sources question over the same revision keeps excluding the uncited criterion", () => {
  const revision = plan("plan-1");
  const derived = derive([revision], { "plan.criterion_traceability": QUESTIONS["plan.criterion_traceability"] });
  const subject = criterion(revision, "crit-a");
  expect(derived.eligibility.filter((item) => item.occurrence_id === subject.occurrence_id)
    .map((item) => `${item.question_id} ${item.decision.tag}`).sort()).toEqual([
    `${ID} eligible`, "plan.criterion_traceability missing_evidence"]);
  expect(derived.exclusions.map((item) => [String(item.question_id), item.occurrence_id, item.reason]))
    .toEqual([["plan.criterion_traceability", subject.occurrence_id, { kind: "uncited" }]]);
});
