"""Tasks 5 and 8: evidence packaging in oakridge's observation app, at `1495ec34`.

Both tasks ship the same slice: the import closure of the Oakridge evidence-package producer,
the runner registry and the question catalogue, with the producer's pure tests. Source moves
from `observation/src/` to `src/` and its selected tests to `tests/visible/`. The workspace
package `canonical-json` keeps its own path and is imported by relative path.

- `subject-only-build` adds a `subject_only` evidence build. Its runtime zod twin of the build
  union is not pointed at by the type checker.
- `addressing-runner` adds an `addressing` code runner fed by a link view the producer builds.
  The runner registry and the producer's hard-coded coverage view are the non-local edits.
"""
# ruff: noqa: E501 - embedded TypeScript keeps the fixture's own line lengths.

from __future__ import annotations

from code_extension.library import HIDDEN_MOVE, RELOCATION, Edit, LibraryTask, Patches, Requirements
from code_extension.slice import Replacement, SliceSpec

_OBS = "observation/"
_CANONICAL = 'from "canonical-json"'

# The relative-import closure of the producer, the runner registry and the catalogue.
_SOURCES = (
    "domain/errors.ts",
    "domain/identity.ts",
    "domain/primitives.ts",
    "grading/catalogue/oakridge-questions.ts",
    "grading/eligibility.ts",
    "grading/evaluator.ts",
    "grading/evidence-packages/capture.ts",
    "grading/evidence-packages/judge-recipe.ts",
    "grading/evidence-packages/pilot-recipe.ts",
    "grading/evidence-packages/recipe.ts",
    "grading/evidence-packages/references.ts",
    "grading/evidence.ts",
    "grading/execution.ts",
    "grading/jobs/budget.ts",
    "grading/observation.ts",
    "grading/question.ts",
    "grading/runner.ts",
    "ports/grade-runner.ts",
    "producers/oakridge/classification.ts",
    "producers/oakridge/evidence-packages.ts",
    "projection/catalogue/oakridge-development.ts",
    "projection/extractor.ts",
    "projection/issues.ts",
    "runners/coverage-checker.ts",
    "runners/deterministic-checker.ts",
    "runners/fastino-glide.ts",
    "runners/jev-direct.ts",
    "runners/llm-judge.ts",
    "runners/stub-model.ts",
)
# Source files that import the workspace package, and how deep each sits under src/.
_CANONICAL_IMPORTERS = {
    "grading/evaluator.ts": "../../",
    "grading/evidence.ts": "../../",
    "grading/execution.ts": "../../",
    "grading/evidence-packages/references.ts": "../../../",
    "producers/oakridge/evidence-packages.ts": "../../../",
    "projection/issues.ts": "../../",
    "runners/deterministic-checker.ts": "../../",
}
# Pinned tests that need no Postgres: name -> how many `"../src/` imports each has.
_VISIBLE_TESTS = {
    "plan-traceability.test.ts": 8,
    "classification.test.ts": 1,
    "extraction-catalogue.test.ts": 3,
    "extraction-issues.test.ts": 3,
}
# Moved to the hidden group: it shows that a pin is read through a runtime schema and that a
# pin the schema refuses surfaces as "no supported captured evidence recipe" (the zod twin
# subject-only-build must find), and it builds an assessment-window package through
# runPackages, the producer path addressing-runner must change.
_RECIPE_DISPATCH = "hidden/regression/tests/hidden/regression/recipe-dispatch.test.ts"
_FIXTURES = ("analysis", "plan", "brief", "assessment")
_PILOT_EXPECTATIONS = '''import { PILOT_QUESTION_IDS, type PilotExpectations } from "../../src/grading/catalogue/oakridge-questions";

// The pinned grading fixture also opens a scratch Postgres database. These tests only read its
// pinned expectations, which are the same for every pilot question, so only those ship.
export const pinnedExpectation = { definition_id: "definition-1", artifact_schema_version: "1" };
export const pilotExpectations = Object.fromEntries(
  PILOT_QUESTION_IDS.map((question_id) => [question_id, pinnedExpectation])) as PilotExpectations;
'''


def _observation_slice(package_name: str, authored_hidden: dict[str, str] | None = None) -> SliceSpec:
    """The one observation slice both tasks ship; only the package name differs."""
    return SliceSpec(
        package_name=package_name,
        files={
            **{f"{_OBS}src/{path}": f"src/{path}" for path in _SOURCES},
            **{f"{_OBS}tests/{name}": f"tests/visible/{name}" for name in _VISIBLE_TESTS},
            f"{_OBS}tests/recipe-dispatch.test.ts": _RECIPE_DISPATCH,
            **{f"{_OBS}fixtures/oakridge/{name}-revision.json": f"fixtures/oakridge/{name}-revision.json"
               for name in _FIXTURES},
            "canonical-json/src/index.ts": "canonical-json/src/index.ts",
        },
        replacements=(
            *(
                Replacement(f"src/{path}", _CANONICAL, f'from "{depth}canonical-json/src/index"')
                for path, depth in _CANONICAL_IMPORTERS.items()
            ),
            *(
                Replacement(f"tests/visible/{name}", '"../src/', '"../../src/', count)
                for name, count in _VISIBLE_TESTS.items()
            ),
            Replacement("tests/visible/plan-traceability.test.ts", '"./grading-fixture"', '"./pilot-expectations"'),
            Replacement("tests/visible/extraction-catalogue.test.ts", "`../fixtures/oakridge/", "`../../fixtures/oakridge/"),
            # Two template strings hold a literal NUL byte, which makes the file binary to the
            # submission check. The escape spells the same runtime string.
            Replacement("src/producers/oakridge/evidence-packages.ts", "\x00", "\\u0000", 2),
            Replacement(_RECIPE_DISPATCH, '"../src/', '"../../../src/', 9),
            Replacement(_RECIPE_DISPATCH, '"./grading-fixture"', '"../../visible/pilot-expectations"'),
        ),
        authored={"tests/visible/pilot-expectations.ts": _PILOT_EXPECTATIONS, **(authored_hidden or {})},
        typecheck_include=("src/**/*.ts", "tests/**/*.ts", "canonical-json/**/*.ts"),
    )


_PILOT = "src/grading/evidence-packages/pilot-recipe.ts"
_PRODUCER = "src/producers/oakridge/evidence-packages.ts"
_CATALOGUE = "src/grading/catalogue/oakridge-questions.ts"
_REGISTRY = "src/grading/runner.ts"
_RUNNER = "src/runners/addressing-checker.ts"

# ---------------------------------------------------------------------------------------
# Task 5: subject_only evidence build
# ---------------------------------------------------------------------------------------

SUBJECT_ONLY_BUILD = _observation_slice("oakridge-observation-subject-only-build")

_SO_UNION: Edit = (
    _PILOT,
    '  | { readonly kind: "assessment_window" }\n'
    '  | { readonly kind: "unscheduled_source"; readonly detail: string };',
    '  | { readonly kind: "assessment_window" }\n'
    '  | { readonly kind: "unscheduled_source"; readonly detail: string }\n'
    "  /** Each supported subject item packaged on its own, from subject slots alone. */\n"
    '  | { readonly kind: "subject_only" };',
)
_SO_SCHEMA: Edit = (
    _PILOT,
    '  z.object({ kind: z.literal("unscheduled_source"), detail: z.string().min(1) }),\n]);',
    '  z.object({ kind: z.literal("unscheduled_source"), detail: z.string().min(1) }),\n'
    '  z.object({ kind: z.literal("subject_only") }),\n]);',
)
_SO_REFINE: Edit = (
    _PILOT,
    '    { message: "linked_sources cannot walk an inward relation" });',
    '    { message: "linked_sources cannot walk an inward relation" })\n'
    "  // subject_only walks nothing, so a pin naming any other slot source is not one it builds.\n"
    '  .refine((recipe) => recipe.build.kind !== "subject_only"\n'
    '    || [...recipe.input, ...recipe.output].every((slot) => slot.source.from === "subject"),\n'
    '    { message: "subject_only packages subject slots alone" });',
)


def _so_builder(hosts: str = "subjects") -> Edit:
    destructure = "subjects" if hosts == "subjects" else "revisions"
    loop = (
        "subjects" if hosts == "subjects"
        else "revisions.filter((revision) => revision.artifact_kind === recipe.subject.artifact_kind)"
    )
    return (
        _PRODUCER,
        "interface SubjectSelection {\n",
        "/** Package each supported subject item on its own, from the subject slots alone. Nothing is\n"
        " * walked, so a subject that declares no links is packaged like any other. */\n"
        f"function subjectOnlyPackages({{ {destructure}, question, recipe }}: BuilderInput): Result<PackageBatch, RunPackageError> {{\n"
        "  const packages: PilotPackage[] = [];\n"
        '  const own = slotsFrom(recipeSlots(recipe), "subject");\n'
        f"  for (const host of {loop}) {{\n"
        "    for (const subject of host.items.filter((item) => item.item_kind === recipe.subject.item_kind)) {\n"
        "      const references = collectReferences(own.map((slot) => reference(slot.role, host.artifact_kind, subject)));\n"
        "      if (!references.ok) return references;\n"
        "      const evidence = packagedEvidenceSet(question.question_id, references.value, null);\n"
        "      if (!evidence.ok) return evidence;\n"
        "      packages.push({ question_id: question.question_id, subject, revision_id: host.revision_id, evidence: evidence.value });\n"
        "    }\n"
        "  }\n"
        "  return ok({ packages, exclusions: [], eligibility: [] });\n"
        "}\n\n"
        "interface SubjectSelection {\n",
    )


_SO_DISPATCH: Edit = (
    _PRODUCER,
    '      : recipe.build.kind === "assessment_window" ? assessmentWindowPackages(input)\n'
    "        : ok(unscheduledSourcePackages(input, recipe.build));",
    '      : recipe.build.kind === "assessment_window" ? assessmentWindowPackages(input)\n'
    '        : recipe.build.kind === "subject_only" ? subjectOnlyPackages(input)\n'
    "          : ok(unscheduledSourcePackages(input, recipe.build));",
)

_SUBJECT_ONLY_PATCHES: Patches = {
    "reference.patch": (
        "Add the build to the union and its runtime schema, refuse non-subject slots, and dispatch to a subject-only builder.",
        (_SO_UNION, _SO_SCHEMA, _SO_REFINE, _so_builder(), _SO_DISPATCH),
    ),
    "unreachable-schema.patch": (
        "The builder and dispatch exist, but the pin schema lacks the build, so no subject_only pin is ever read.",
        (_SO_UNION, _so_builder(), _SO_DISPATCH),
    ),
    "wrong-all-revisions.patch": (
        "The builder packages every revision of the subject kind, not only those whose provenance is supported.",
        (_SO_UNION, _SO_SCHEMA, _SO_REFINE, _so_builder("revisions"), _SO_DISPATCH),
    ),
    "wrong-accepts-linked-slots.patch": (
        "The pin schema reads a subject_only pin that names a linked or unscheduled slot instead of refusing it.",
        (_SO_UNION, _SO_SCHEMA, _so_builder(), _SO_DISPATCH),
    ),
}

_SUBJECT_ONLY_REQUIREMENTS: Requirements = (
    ("A recipe may pin the build { kind: \"subject_only\" }, and such a pin is read as a supported "
     "slot recipe.", ("pin-is-readable",)),
    ("runPackages packages every subject item of each supported subject revision on its own, "
     "even when it declares no links, and marks it eligible.",
     ("uncited-subject-packaged", "every-subject-alone", "other-question-unchanged")),
    ("A subject_only package holds only the subject slots' captured references and is "
     "complete.", ("subject-reference-only",)),
    ("A revision with unsupported provenance keeps its inapplicable decisions and gets no "
     "package.", ("inapplicable-not-packaged",)),
    ("A subject_only pin that declares a linked or unscheduled slot is not a readable pin.",
     ("non-subject-slot-refused",)),
)

# ---------------------------------------------------------------------------------------
# Task 8: addressing code runner fed by a producer-built link view
# ---------------------------------------------------------------------------------------

_COVERAGE_PIN = "hidden/regression/tests/hidden/regression/coverage-link-view.test.ts"
_COVERAGE_PIN_TEST = '''import { expect, test } from "bun:test";
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
'''

ADDRESSING_RUNNER = _observation_slice(
    "oakridge-observation-addressing-runner", {_COVERAGE_PIN: _COVERAGE_PIN_TEST},
)

_AD_ROLE: Edit = (
    _PILOT,
    '"plan_criterion", "brief_criterion", "assessment_finding"] as const;',
    '"plan_criterion", "brief_criterion", "assessment_finding", "proposed_spec_update"] as const;',
)
_AD_RECIPE: Edit = (
    _PILOT,
    '    { link_type: "assesses", direction: "in", artifact_kind: "assessment", item_kind: "assessment_finding" }, 0, 100)],\n};\n',
    '    { link_type: "assesses", direction: "in", artifact_kind: "assessment", item_kind: "assessment_finding" }, 0, 100)],\n};\n\n'
    "/** Proposed spec updates name the findings they address, so the relation points inward and the\n"
    " * analysis revision that holds the updates is found by capture window, as for coverage. */\n"
    "export const ANALYSIS_ADDRESSING_RECIPE: PilotEvidenceRecipe = {\n"
    '  recipe_version: "v1", subject: { artifact_kind: "analysis", item_kind: "finding" },\n'
    '  build: { kind: "assessment_window" },\n'
    '  input: [subjectSlot("analysis_finding")],\n'
    '  output: [linkedSlot("proposed_spec_update",\n'
    '    { link_type: "addresses", direction: "in", artifact_kind: "analysis", item_kind: "proposed_spec_update" }, 0, 100)],\n'
    "};\n",
)
_AD_CATALOGUE: tuple[Edit, ...] = (
    (_CATALOGUE,
     "import { ANALYSIS_RELEVANCE_RECIPE, ASSESSMENT_COVERAGE_RECIPE,",
     "import { ANALYSIS_ADDRESSING_RECIPE, ANALYSIS_RELEVANCE_RECIPE, ASSESSMENT_COVERAGE_RECIPE,"),
    (_CATALOGUE,
     '  "brief.source_fidelity", "assessment.coverage"] as const;',
     '  "brief.source_fidelity", "assessment.coverage", "analysis.finding_addressing"] as const;'),
    (_CATALOGUE,
     "\n/** Four independently versioned questions,",
     "\nconst addressing: Omit<QuestionDefinition, \"pinned_expectation\"> = {\n"
     '  question_id: "analysis.finding_addressing" as QuestionId, question_version: "v1", target_item_kinds: ["finding"],\n'
     "  input_recipe: pinnedInputRecipe(ANALYSIS_ADDRESSING_RECIPE),\n"
     '  response_kind: "boolean", allowed_values: null, missing_evidence_policy: "fail",\n'
     '  abstain_semantics: "No answer is recorded when the finding or the proposed spec updates are unavailable; zero addressing updates is a negative answer.",\n'
     '  unclear_semantics: "Link absence is not unknown: an update that does not list the finding id does not address it.",\n'
     '  interpretation_caveats: "Only a proposed spec update whose finding_ids names this finding addresses it; a related section or wording is not an address.",\n'
     "  requires_repository_snapshot: false,\n"
     "};\n\n"
     "/** Four independently versioned questions,"),
    (_CATALOGUE,
     '    "assessment.coverage": pinnedQuestion(coverage, "Does at least one assessment finding explicitly assess this brief criterion?", expectations["assessment.coverage"]),\n',
     '    "assessment.coverage": pinnedQuestion(coverage, "Does at least one assessment finding explicitly assess this brief criterion?", expectations["assessment.coverage"]),\n'
     '    "analysis.finding_addressing": pinnedQuestion(addressing, "Is this analysis finding addressed by at least one proposed spec update?", expectations["analysis.finding_addressing"]),\n'),
)

_AD_MATCH = (
    'link.type === "addresses" && link.target_artifact_kind === "analysis" && link.target_item_kind === "finding"\n'
    "    && link.target_scope === finding.item_scope && link.target_local_id === finding.producer_local_id"
)
_AD_MATCH_ANY_TYPE = (
    'link.target_artifact_kind === "analysis" && link.target_item_kind === "finding"\n'
    "    && link.target_scope === finding.item_scope && link.target_local_id === finding.producer_local_id"
)
_AD_MATCH_ANY_SCOPE = (
    'link.type === "addresses" && link.target_artifact_kind === "analysis" && link.target_item_kind === "finding"\n'
    "    && link.target_local_id === finding.producer_local_id"
)


def _ad_runner(match: str = _AD_MATCH) -> Edit:
    return (_RUNNER, "", '''import { pinnedPilotRecipe } from "../grading/evidence-packages/pilot-recipe";
import { err, ok, type JsonValue, type Result } from "../domain/primitives";
import type { EvaluationOutcome, GradingContext, GradingError, RunnerResult } from "../grading/runner";
import type { GradeRunner } from "../ports/grade-runner";
import type { LinkReference, SelectedItem } from "../projection/extractor";

/** The small link view mirrors analysis.findings and analysis.proposed_updates selections. */
export interface AddressedFinding {
  readonly item_kind: "finding";
  readonly item_scope: string;
  readonly producer_local_id: string;
}
export type AddressingLink = Pick<LinkReference, "type" | "target_artifact_kind" | "target_item_kind" | "target_scope" | "target_local_id">;
export interface AddressingUpdate {
  readonly item_kind: "proposed_spec_update";
  readonly links: readonly AddressingLink[];
}
export interface AddressingInput {
  readonly analysis_finding: AddressedFinding;
  readonly proposed_spec_updates: readonly AddressingUpdate[];
}

export function addressingInput(finding: SelectedItem, updates: readonly SelectedItem[]): Result<AddressingInput, GradingError> {
  if (finding.item_kind !== "finding" || !finding.item_scope || !finding.producer_local_id)
    return err({ operation: "addressing_input", entity_id: finding.item_id_or_path,
      detail: "subject must have a scoped analysis finding identity" });
  if (updates.some((update) => update.item_kind !== "proposed_spec_update"))
    return err({ operation: "addressing_input", entity_id: finding.item_id_or_path,
      detail: "all addressing candidates must be proposed spec updates" });
  return ok({ analysis_finding: { item_kind: "finding", item_scope: finding.item_scope, producer_local_id: finding.producer_local_id },
    proposed_spec_updates: updates.map((update) => ({ item_kind: "proposed_spec_update", links: update.links.map((link) => ({
      type: link.type, target_artifact_kind: link.target_artifact_kind, target_item_kind: link.target_item_kind,
      target_scope: link.target_scope, target_local_id: link.target_local_id })) })) });
}

/** Only an explicit addresses link naming this finding counts; a shared section is not an address. */
export function checkFindingAddressed(input: AddressingInput): Result<EvaluationOutcome, GradingError> {
  const finding = input.analysis_finding;
  const addressing = input.proposed_spec_updates.filter((update) => update.links.some((link) =>
    @MATCH@));
  return ok({ answer: { state: "answered", kind: "boolean", value: addressing.length > 0 },
    rationale: `${addressing.length} proposed spec updates explicitly address analysis finding ${finding.producer_local_id}` });
}

function isObject(value: JsonValue): value is { readonly [key: string]: JsonValue } {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** Decode the small, local link view stored in the first addressing evidence reference. */
export function decodeAddressingInput(value: JsonValue): Result<AddressingInput, GradingError> {
  const invalid = () => err({ operation: "decode_addressing_input", entity_id: "assessment_window",
    detail: "addressing evidence must contain an analysis finding and proposed spec update links" });
  if (!isObject(value) || !isObject(value.analysis_finding) || !Array.isArray(value.proposed_spec_updates)) return invalid();
  const finding = value.analysis_finding;
  if (finding.item_kind !== "finding" || typeof finding.item_scope !== "string"
    || typeof finding.producer_local_id !== "string") return invalid();
  const updates: AddressingUpdate[] = [];
  for (const candidate of value.proposed_spec_updates) {
    if (!isObject(candidate) || candidate.item_kind !== "proposed_spec_update" || !Array.isArray(candidate.links)) return invalid();
    const links: AddressingLink[] = [];
    for (const link of candidate.links) {
      if (!isObject(link) || typeof link.type !== "string" || typeof link.target_artifact_kind !== "string"
        || typeof link.target_item_kind !== "string" || (link.target_scope !== null && typeof link.target_scope !== "string")
        || typeof link.target_local_id !== "string") return invalid();
      links.push({ type: link.type as LinkReference["type"], target_artifact_kind: link.target_artifact_kind,
        target_item_kind: link.target_item_kind, target_scope: link.target_scope, target_local_id: link.target_local_id });
    }
    updates.push({ item_kind: "proposed_spec_update", links });
  }
  return ok({ analysis_finding: { item_kind: "finding", item_scope: finding.item_scope,
    producer_local_id: finding.producer_local_id }, proposed_spec_updates: updates });
}

export function runAddressingCheck(context: GradingContext): RunnerResult {
  // Bind to the pinned contract, as coverage does: a boolean question whose pin builds an
  // assessment window over proposed spec updates produces the view this runner decodes.
  if (pinnedPilotRecipe(context.question)?.build.kind !== "assessment_window"
    || context.question.response_kind !== "boolean")
    return err({ operation: "finding_addressing", entity_id: context.question.question_id,
      detail: "addressing runner requires a boolean question pinning an assessment window" });
  const content = context.evidence.references[0]?.content;
  if (content === undefined) return err({ operation: "finding_addressing", entity_id: context.evidence.evidence_set_id,
    detail: "addressing link evidence is absent" });
  const decoded = decodeAddressingInput(content);
  return decoded.ok ? checkFindingAddressed(decoded.value) : decoded;
}

export const addressingChecker: GradeRunner = { kind: "code", run: async (context) => runAddressingCheck(context) };
'''.replace("@MATCH@", match))


_AD_REGISTRY: tuple[Edit, ...] = (
    (_REGISTRY,
     'import { coverageChecker } from "../runners/coverage-checker";\n',
     'import { coverageChecker } from "../runners/coverage-checker";\n'
     'import { addressingChecker } from "../runners/addressing-checker";\n'),
    (_REGISTRY,
     '  coverage: { kind: "code", network: false, factory: () => coverageChecker },\n',
     '  coverage: { kind: "code", network: false, factory: () => coverageChecker },\n'
     '  addressing: { kind: "code", network: false, factory: () => addressingChecker },\n'),
)
_AD_PRODUCER: tuple[Edit, ...] = (
    (_PRODUCER,
     'import { coverageInput, type CoverageInput } from "../../runners/coverage-checker";\n',
     'import { coverageInput, type CoverageInput } from "../../runners/coverage-checker";\n'
     'import { addressingInput, type AddressingInput } from "../../runners/addressing-checker";\n'),
    (_PRODUCER,
     "/** The pinned relation points inward, so the source revision is found by capture window rather\n",
     "/** The addressing view, like the coverage view, has its own digest and precedes the captured\n"
     " * source references in the package. */\n"
     "function addressingLinkReference(subject: CapturedItem, links: AddressingInput): Result<EvidenceReference, EvidencePackageError> {\n"
     "  const digest = canonicalDigest(links);\n"
     '  if (!digest.ok) return err({ operation: "evidence_packages", entity_id: subject.occurrence_id,\n'
     "    detail: digest.error.detail });\n"
     '  return ok({ ref: `addressing_links:${subject.occurrence_id}`, kind: "internal",\n'
     "    content: links as unknown as JsonValue, digest: digest.value });\n"
     "}\n\n"
     "/** The link view a window question's code runner decodes, chosen by the item kind the pinned\n"
     " * inward relation reaches: proposed spec updates for addressing, assessment findings for coverage. */\n"
     "function windowLinkReference(subject: CapturedItem, relation: LinkRelation, found: readonly CapturedItem[])\n"
     "  : Result<EvidenceReference, EvidencePackageError> {\n"
     '  if (relation.item_kind === "proposed_spec_update") {\n'
     "    const view = addressingInput(subject, found);\n"
     "    return view.ok ? addressingLinkReference(subject, view.value)\n"
     '      : err({ operation: "evidence_packages", entity_id: subject.occurrence_id, detail: view.error.detail });\n'
     "  }\n"
     "  const links = coverageInput(subject, found);\n"
     "  return links.ok ? coverageLinkReference(subject, links.value)\n"
     '    : err({ operation: "evidence_packages", entity_id: subject.occurrence_id, detail: links.error.detail });\n'
     "}\n\n"
     "/** The pinned relation points inward, so the source revision is found by capture window rather\n"),
    (_PRODUCER,
     "        const links = coverageInput(subject, found);\n"
     '        if (!links.ok) return err({ operation: "evidence_packages", entity_id: subject.occurrence_id,\n'
     "          detail: links.error.detail });\n"
     "        const references = collectReferences([\n"
     "          coverageLinkReference(subject, links.value),\n",
     "        const references = collectReferences([\n"
     "          windowLinkReference(subject, relation, found),\n"),
)
_AD_CORE = (_AD_ROLE, _AD_RECIPE, *_AD_CATALOGUE)

_ADDRESSING_PATCHES: Patches = {
    "reference.patch": (
        "Add the role, recipe and catalogue question, the addressing runner and its registry entry, and the producer's addressing link view.",
        (*_AD_CORE, _ad_runner(), *_AD_REGISTRY, *_AD_PRODUCER),
    ),
    "unreachable-registry.patch": (
        "Everything but the registry entry: the runner exists, but no grading path can name it.",
        (*_AD_CORE, _ad_runner(), *_AD_PRODUCER),
    ),
    "unreachable-producer.patch": (
        "The runner is registered, but the producer still builds only the coverage view, so packaging an addressing question fails.",
        (*_AD_CORE, _ad_runner(), *_AD_REGISTRY),
    ),
    "wrong-link-type.patch": (
        "The runner counts a link of any type that names the finding, not only addresses links.",
        (*_AD_CORE, _ad_runner(_AD_MATCH_ANY_TYPE), *_AD_REGISTRY, *_AD_PRODUCER),
    ),
    "wrong-scope.patch": (
        "The runner matches the finding by local id alone and ignores the link's target scope.",
        (*_AD_CORE, _ad_runner(_AD_MATCH_ANY_SCOPE), *_AD_REGISTRY, *_AD_PRODUCER),
    ),
}

_ADDRESSING_REQUIREMENTS: Requirements = (
    ("The catalogue pins analysis.finding_addressing: a boolean question over analysis findings "
     "with the stated assessment-window recipe.", ("catalogue-question",)),
    ("An addressing code runner without network is registered, so grading can name it.",
     ("runner-registered",)),
    ("runPackages packages each analysis finding with an addressing link view, its own reference "
     "and the updates that address it, and the runner answers true exactly when an update addresses "
     "the finding.", ("addressed-answers-true", "unaddressed-answers-false", "link-view-contract",
                      "shared-update-in-both-views")),
    ("The runner counts only addresses links whose target names the finding's artifact kind, item "
     "kind, scope and local id.", ("only-addresses-links", "scope-must-match", "other-finding-not-counted")),
    ("The runner refuses a non-boolean question and a view that is not an addressing link view.",
     ("refuses-coverage-view", "refuses-non-boolean")),
)

_NUL_ESCAPE = (
    "Two literal NUL bytes in the producer's template strings are written as the \\u0000 escape, "
    "which is the same runtime string, so a submission that edits the file is not refused as binary."
)

TASKS = (
    LibraryTask(
        scenario="subject-only-build",
        slice=SUBJECT_ONLY_BUILD,
        patches=_SUBJECT_ONLY_PATCHES,
        requirements=_SUBJECT_ONLY_REQUIREMENTS,
        feature_tokens=("subject_only",),
        local_adaptations=(
            RELOCATION,
            "The pinned grading fixture opens a scratch Postgres database; the one value the shipped "
            "tests read from it, the pilot pinned expectations, is replaced by an authored helper that "
            "gives every catalogue question the same expectation.",
            _NUL_ESCAPE,
            HIDDEN_MOVE,
        ),
    ),
    LibraryTask(
        scenario="addressing-runner",
        slice=ADDRESSING_RUNNER,
        patches=_ADDRESSING_PATCHES,
        requirements=_ADDRESSING_REQUIREMENTS,
        feature_tokens=("addressing",),
        local_adaptations=(
            RELOCATION,
            "The pinned grading fixture opens a scratch Postgres database; the one value the shipped "
            "tests read from it, the pilot pinned expectations, is replaced by an authored helper that "
            "gives every catalogue question the same expectation.",
            _NUL_ESCAPE,
            HIDDEN_MOVE,
            "An authored hidden regression test pins the coverage link view's bytes and digests, "
            "because evidence-set digests depend on them.",
        ),
    ),
)
