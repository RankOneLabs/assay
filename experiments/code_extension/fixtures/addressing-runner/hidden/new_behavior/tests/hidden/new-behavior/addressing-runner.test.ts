import { expect, test } from "bun:test";
import { canonicalDigest } from "../../../canonical-json/src/index";
import type { EvidenceSetId, ItemOccurrenceId } from "../../../src/domain/identity";
import type { JsonValue } from "../../../src/domain/primitives";
import { oakridgeQuestions, PILOT_QUESTION_IDS, type PilotExpectations, type PilotQuestion } from "../../../src/grading/catalogue/oakridge-questions";
import type { EvaluatorDefinition } from "../../../src/grading/evaluator";
import type { EvidenceSet } from "../../../src/grading/evidence";
import type { CapturedRevision } from "../../../src/grading/evidence-packages/capture";
import type { QuestionDefinition } from "../../../src/grading/question";
import { runnerEntry, runnerNames } from "../../../src/grading/runner";
import { runPackages } from "../../../src/producers/oakridge/evidence-packages";
import { oakridgeDevelopmentCatalogue } from "../../../src/projection/catalogue/oakridge-development";
import { selectRevision } from "../../../src/projection/extractor";

// Inlined rather than imported from the pinned grading fixture, which opens Postgres.
const expectation = { definition_id: "definition-1", artifact_schema_version: "1" };
const expectations = Object.fromEntries(PILOT_QUESTION_IDS.map((id) => [id, expectation])) as PilotExpectations;
const ID = "analysis.finding_addressing";
const evaluator: EvaluatorDefinition = { evaluator_definition_id: "code", kind: "code", backend_kind: "local",
  provider: "fixture-code", model: null, instruction_text: "prompt-1", prompt_digest: "prompt", config_digest: "config-1",
  runtime_revision: "1", cost_metadata: null, seed: null, attempt_controls: null };

function addressingQuestion(): PilotQuestion {
  const question = (oakridgeQuestions(expectations) as unknown as Record<string, PilotQuestion | undefined>)[ID];
  if (!question) throw new Error(`the catalogue has no ${ID} question`);
  return question;
}
function runner() {
  const entry = runnerEntry("addressing");
  if (!entry) throw new Error("no addressing runner is registered");
  return entry.factory(0, {});
}

function captured(revision_id: string, body: JsonValue, at = "2026-11-01T00:00:00Z"): CapturedRevision {
  const pass = selectRevision(body, revision_id, oakridgeDevelopmentCatalogue("analysis", "development-v1"));
  return { ...expectation, revision_id, unit_id: "analysis/run-1", artifact_kind: "analysis", recorded_at: new Date(at),
    items: pass.items.map(({ item }, index) => ({ ...item, revision_id, occurrence_id: `${revision_id}-${index}` as ItemOccurrenceId })) };
}
const update = (section: string, finding_ids: readonly string[]) => ({ section, change: "Clarify", reason: "Finding", finding_ids });
/** Findings a, b and c; one update addresses a, another addresses a and b, and none addresses c. */
const analysis = captured("analysis-1", { summary: "Review", source_spec_refs: [],
  findings: [{ id: "finding-a", description: "Missing case", severity: "warning" },
    { id: "finding-b", description: "Timing", severity: "info" }, { id: "finding-c", description: "Naming", severity: "info" }],
  requirements: [], risks: [], proposed_spec_updates: [update("Behavior", ["finding-a"]), update("Timing", ["finding-a", "finding-b"])] });
const finding = (local_id: string) => analysis.items.find((item) => item.item_kind === "finding" && item.producer_local_id === local_id)!;

function packaged(local_id: string) {
  const result = runPackages([analysis], { [ID]: addressingQuestion() });
  if (!result.ok) throw new Error(result.error.detail);
  const subject = finding(local_id);
  const pack = result.value.packages.find((item) => item.subject.occurrence_id === subject.occurrence_id);
  if (!pack) throw new Error(`finding ${local_id} has no package`);
  const decision = result.value.eligibility.find((item) => item.question_id === ID && item.occurrence_id === subject.occurrence_id)?.decision;
  return { pack, decision, subject };
}
async function answer(evidence: EvidenceSet, question: QuestionDefinition = addressingQuestion().definition): Promise<unknown> {
  const result = await runner().run({ question, evidence, evaluator });
  return result.ok ? result.value.answer : { error: result.error.detail };
}
const link = (overrides: Record<string, unknown> = {}) => ({ type: "addresses", target_artifact_kind: "analysis",
  target_item_kind: "finding", target_scope: "analysis/finding", target_local_id: "finding-a", ...overrides });
function view(links: readonly unknown[]): EvidenceSet {
  const content = { analysis_finding: { item_kind: "finding", item_scope: "analysis/finding", producer_local_id: "finding-a" },
    proposed_spec_updates: [{ item_kind: "proposed_spec_update", links }] };
  return { evidence_set_id: "evidence-1" as EvidenceSetId, is_incomplete: false, incompleteness_reason: null,
    references: [{ ref: "addressing_links:finding", kind: "internal", content: content as JsonValue, digest: null }] };
}
const TRUE = { state: "answered", kind: "boolean", value: true };
const FALSE = { state: "answered", kind: "boolean", value: false };

test("reachability: an addressing code runner without network is registered", () => {
  expect((runnerNames as readonly string[]).includes("addressing")).toBe(true);
  const entry = runnerEntry("addressing");
  expect([entry?.kind, entry?.network, entry?.factory(0, {}).kind]).toEqual(["code", false, "code"]);
});

test("reachability: a finding a proposed spec update addresses is answered true from its captured package", async () => {
  const { pack, decision } = packaged("finding-a");
  expect(decision).toEqual({ tag: "eligible", payload: { evidence_set_id: pack.evidence.evidence_set_id } });
  expect(await answer(pack.evidence)).toEqual(TRUE);
});

test("reachability: a finding no proposed spec update addresses is packaged and answered false", async () => {
  const { pack, decision } = packaged("finding-c");
  expect(decision?.tag).toBe("eligible");
  expect(await answer(pack.evidence)).toEqual(FALSE);
});

test("semantics: the catalogue pins a boolean question over analysis findings with the stated recipe", () => {
  const { definition } = addressingQuestion();
  expect({ ...definition, abstain_semantics: undefined, unclear_semantics: undefined, interpretation_caveats: undefined, question_text: undefined } as unknown)
    .toEqual({ question_id: ID, question_version: "v1", pinned_expectation: expectation, target_item_kinds: ["finding"],
      response_kind: "boolean", allowed_values: null, missing_evidence_policy: "fail", requires_repository_snapshot: false,
      abstain_semantics: undefined, unclear_semantics: undefined, interpretation_caveats: undefined, question_text: undefined,
      input_recipe: { recipe_version: "v1", build: { kind: "assessment_window" }, subject: { artifact_kind: "analysis", item_kind: "finding" },
        input: [{ role: "analysis_finding", source: { from: "subject" }, min_count: 1, max_count: 1 }],
        output: [{ role: "proposed_spec_update", source: { from: "linked", link_type: "addresses", direction: "in",
          artifact_kind: "analysis", item_kind: "proposed_spec_update" }, min_count: 0, max_count: 100 }] } });
});

test("semantics: the package carries the addressing link view first, then the finding, then the updates that address it", () => {
  const { pack, subject } = packaged("finding-b");
  const content = { analysis_finding: { item_kind: "finding", item_scope: "analysis/finding", producer_local_id: "finding-b" },
    proposed_spec_updates: [{ item_kind: "proposed_spec_update", links: [link(), link({ target_local_id: "finding-b" })] }] };
  const digest = canonicalDigest(content);
  expect(pack.evidence.references[0]).toEqual({ ref: `addressing_links:${subject.occurrence_id}`, kind: "internal",
    content, digest: digest.ok ? digest.value : "unreachable" });
  expect(pack.evidence.references.map((ref) => ref.ref)).toEqual([`addressing_links:${subject.occurrence_id}`,
    "analysis_finding:finding-b", "proposed_spec_update:/proposed_spec_updates/1"]);
  expect([pack.evidence.is_incomplete, pack.revision_id]).toEqual([false, "analysis-1"]);
});

test("semantics: an update addressing two findings is in both views, and each view lists only the updates that address it", async () => {
  const a = packaged("finding-a").pack;
  const c = packaged("finding-c").pack;
  expect([a, c].map((pack) => (pack.evidence.references[0]?.content as { proposed_spec_updates: unknown[] }).proposed_spec_updates.length))
    .toEqual([2, 0]);
  expect(await answer(packaged("finding-b").pack.evidence)).toEqual(TRUE);
});

test("semantics: only an addresses link counts", async () => {
  expect(await answer(view([link({ type: "derived_from" }), link({ type: "assesses" })]))).toEqual(FALSE);
  expect(await answer(view([link({ type: "derived_from" }), link()]))).toEqual(TRUE);
});

test("semantics: a link must name the finding's scope", async () => {
  expect(await answer(view([link({ target_scope: "cohort/alpha/finding" }), link({ target_scope: null })]))).toEqual(FALSE);
});

test("semantics: a link to another finding, item kind or artifact kind does not count", async () => {
  expect(await answer(view([link({ target_local_id: "finding-b" }), link({ target_item_kind: "requirement_status" }),
    link({ target_artifact_kind: "plan" })]))).toEqual(FALSE);
});

test("semantics: the runner refuses a coverage link view", async () => {
  const coverage = { brief_criterion: { item_kind: "criterion", item_scope: "cohort/alpha/criterion", producer_local_id: "crit-a" },
    assessment_findings: [{ item_kind: "assessment_finding", links: [] }] };
  const evidence: EvidenceSet = { ...view([]), references: [{ ref: "coverage_links:x", kind: "internal", content: coverage, digest: null }] };
  expect(await answer(evidence)).toHaveProperty("error");
});

test("semantics: the runner refuses a question that is not boolean", async () => {
  const question = { ...addressingQuestion().definition, response_kind: "choice" as const, allowed_values: ["yes", "no"] };
  expect(await answer(view([link()]), question)).toHaveProperty("error");
});
