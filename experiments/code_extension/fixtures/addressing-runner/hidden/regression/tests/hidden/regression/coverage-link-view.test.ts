import { expect, test } from "bun:test";
import { canonicalDigest } from "../../../canonical-json/src/index";
import type { ItemOccurrenceId } from "../../../src/domain/identity";
import type { JsonValue } from "../../../src/domain/primitives";
import { oakridgeQuestions, PILOT_QUESTION_IDS, type PilotExpectations } from "../../../src/grading/catalogue/oakridge-questions";
import type { EvaluatorDefinition } from "../../../src/grading/evaluator";
import type { CapturedRevision } from "../../../src/grading/evidence-packages/capture";
import { runnerEntry } from "../../../src/grading/runner";
import { runPackages } from "../../../src/producers/oakridge/evidence-packages";
import { oakridgeDevelopmentCatalogue } from "../../../src/projection/catalogue/oakridge-development";
import { selectRevision } from "../../../src/projection/extractor";

// Evidence-set digests are computed over the coverage link view, so its bytes must not move.
// The digests were computed at the pin, before any addressing change.
const VIEW_DIGEST = "canonical-json/v1:6c5ea6352bbb1d10e2b8a6aa2363899c6b84d338256fd86cc043d5ab9427efa3";
const EMPTY_DIGEST = "canonical-json/v1:0f7fc3819d8416d7a4cbce569917d4679d9c27d2efa863a8a7c4a76386cd06ce";
const expectation = { definition_id: "definition-1", artifact_schema_version: "1" };
const expectations = Object.fromEntries(PILOT_QUESTION_IDS.map((id) => [id, expectation])) as PilotExpectations;
const coverage = oakridgeQuestions(expectations)["assessment.coverage"];
const evaluator: EvaluatorDefinition = { evaluator_definition_id: "code", kind: "code", backend_kind: "local",
  provider: "fixture-code", model: null, instruction_text: "prompt-1", prompt_digest: "prompt", config_digest: "config-1",
  runtime_revision: "1", cost_metadata: null, seed: null, attempt_controls: null };

function captured(artifact_kind: string, revision_id: string, unit_id: string, body: JsonValue, at: string): CapturedRevision {
  const pass = selectRevision(body, revision_id, oakridgeDevelopmentCatalogue(artifact_kind, "development-v1", { unit_id }));
  return { ...expectation, revision_id, unit_id, artifact_kind, recorded_at: new Date(at),
    items: pass.items.map(({ item }, index) => ({ ...item, revision_id, occurrence_id: `${revision_id}-${index}` as ItemOccurrenceId })) };
}

const brief = captured("brief", "brief-1", "briefs/alpha", { cohort_id: "alpha", decisions_made: [], approaches_rejected: [],
  acceptance_criteria: [{ id: "crit-a", text: "Works" }, { id: "crit-b", text: "Fails closed" }] }, "2026-11-01T00:00:00Z");
const assessment = captured("assessment", "assessment-1", "implementation/alpha", { head_sha: "reviewed",
  findings: [{ criterion_id: "crit-a", evidence: [] }, { description: "integration", evidence: [] }] }, "2026-11-01T01:00:00Z");

function packages() {
  const result = runPackages([brief, assessment], { "assessment.coverage": coverage });
  if (!result.ok) throw new Error(result.error.detail);
  return result.value.packages;
}

test("the coverage link view keeps its pinned shape, digest and evidence set", () => {
  const [first, second] = packages();
  const view = { brief_criterion: { item_kind: "criterion", item_scope: "cohort/alpha/criterion", producer_local_id: "crit-a" },
    assessment_findings: [{ item_kind: "assessment_finding", links: [{ type: "assesses", target_artifact_kind: "brief",
      target_item_kind: "criterion", target_scope: "cohort/alpha/criterion", target_local_id: "crit-a" }] }] };
  const empty = { brief_criterion: { item_kind: "criterion", item_scope: "cohort/alpha/criterion", producer_local_id: "crit-b" },
    assessment_findings: [] };
  expect([first?.evidence.references[0], second?.evidence.references[0]]).toEqual([
    { ref: "coverage_links:brief-1-0", kind: "internal", content: view, digest: VIEW_DIGEST },
    { ref: "coverage_links:brief-1-1", kind: "internal", content: empty, digest: EMPTY_DIGEST }]);
  expect([canonicalDigest(view), canonicalDigest(empty)] as unknown)
    .toEqual([{ ok: true, value: VIEW_DIGEST }, { ok: true, value: EMPTY_DIGEST }]);
  expect([first, second].map((pack) => pack?.evidence.references.map((ref) => ref.ref))).toEqual([
    ["coverage_links:brief-1-0", "brief_criterion:crit-a", "assessment_finding:/findings/0"],
    ["coverage_links:brief-1-1", "brief_criterion:crit-b"]]);
  expect([String(first?.evidence.evidence_set_id), String(second?.evidence.evidence_set_id)]).toEqual([
    "canonical-json/v1:f5e1b0b47a051aae871565fb03b8e7158b1a6336f5e032bc98703f5b08fc8336",
    "canonical-json/v1:68f011d9e43e4d1f57f2c81912b682ac169832eb5599d3b350a928047e87b4dd"]);
});

test("the coverage runner still answers from the packaged view", async () => {
  const runner = runnerEntry("coverage")!.factory(0, {});
  const answers = await Promise.all(packages().map((pack) => runner.run({ question: coverage.definition, evidence: pack.evidence, evaluator })));
  expect(answers.map((answer) => answer.ok && answer.value.answer)).toEqual([
    { state: "answered", kind: "boolean", value: true }, { state: "answered", kind: "boolean", value: false }]);
});
