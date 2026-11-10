import { expect, test } from "bun:test";
import type { ItemOccurrenceId } from "../../../src/domain/identity";
import type { RedactionPolicy } from "../../../src/export/manifest";
import { instructionDigest } from "../../../src/grading/evaluator";
import type { EvidenceKind } from "../../../src/grading/evidence";
import type { CapturedItem } from "../../../src/grading/evidence-packages/capture";
import { capturedReference } from "../../../src/grading/evidence-packages/references";
import { createApp } from "../../../src/http/app";
import { contextSchema } from "../../../src/http/evaluations";
import { evidenceKindForCapturedPath } from "../../../src/producers/oakridge/classification";
import type { Database } from "../../../src/storage/database";
import { prepareRows, type ExportRows } from "../../../src/storage/export-store";

const tenant = { producer: "oakridge", namespace: "restricted-test" };
const selection = { run_id: null, occurrence_ids: null };
const identity = { manifest_id: "restricted", frozen_at: "2026-01-01T00:00:00.000Z" };
const RESTRICTED = "PRIVATE FILES IN SCOPE";
const SOURCE = "PRIVATE SOURCE";
/** Not an EvidenceKind until the task adds it. */
const RESTRICTED_KIND = "restricted" as unknown as EvidenceKind;
const restrictedPath = "/evidence_set/evidence_refs/0/content";
const repositoryPath = "/evidence_set/evidence_refs/1/content";

/** A policy as callers before this change build it: no restricted flag at all. */
const closed = { target_name: "assay", allow_raw_build_output: false, allow_raw_test_output: false,
  allow_repository_content: false } as RedactionPolicy;
const allowing = (extra: Record<string, boolean>): RedactionPolicy => ({ ...closed, ...extra }) as unknown as RedactionPolicy;

function rows(evidence_refs: unknown): ExportRows {
  return {
    revisions: [{ ...tenant, revision_id: "rev", artifact_kind: "brief", body_digest:
      "canonical-json/v1:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", body: { cohort_id: "c1" } }],
    occurrences: [{ ...tenant, occurrence_id: "occ", revision_id: "rev", run_id: "run", item_selector: "/cohort_id",
      selected_value: { cohort_id: "c1" } }],
    evidences: [{ ...tenant, evidence_set_id: "evidence", evidence_refs, is_incomplete: false, incompleteness_reason: null }],
    grades: [{ ...tenant, observation_id: "grade", execution_id: "exec", subject_occurrence_id: "occ", evidence_set_id: "evidence",
      question_id: "q", question_version: "1", evaluator_definition_id: "human", answer_state: "answered", answer_payload: {} }],
    executions: [{ ...tenant, execution_id: "exec", question_id: "q", evaluator_definition_id: "human" }],
    evaluators: [{ ...tenant, evaluator_definition_id: "human", kind: "human", identity_digest: "digest" }],
    questions: [{ ...tenant, question_id: "q", question_version: "1", input_recipe: {}, response_kind: "boolean" }],
  } as unknown as ExportRows;
}
const bothKinds = [{ ref: "scope", kind: "restricted", content: RESTRICTED, digest: null },
  { ref: "repo", kind: "repository_content", content: SOURCE, digest: null }];

function exported(evidence_refs: unknown, policy: RedactionPolicy) {
  const prepared = prepareRows(rows(evidence_refs), tenant, selection, policy, identity);
  return { text: JSON.stringify(prepared.records), reasons: prepared.manifest.membership[0]?.redaction_reasons ?? [] };
}

/** The grade-context intake body, carrying one restricted evidence reference. */
function intake(): unknown {
  return contextSchema.parse({
    question: { question_id: "q", question_version: "1", pinned_expectation: { definition_id: "fixture-definition",
      artifact_schema_version: "development-v1" }, target_item_kinds: ["brief"], input_recipe: {},
      response_kind: "boolean", allowed_values: null, missing_evidence_policy: "fail", abstain_semantics: "",
      unclear_semantics: "", interpretation_caveats: "", requires_repository_snapshot: false },
    evidence: { evidence_set_id: "evidence", references: [{ ref: "scope", kind: "restricted", content: RESTRICTED, digest: null }],
      is_incomplete: false, incompleteness_reason: null },
    evaluator: { evaluator_definition_id: "human", kind: "human", backend_kind: "local", provider: "fixture",
      model: null, instruction_text: "", prompt_digest: instructionDigest(""), config_digest: "", runtime_revision: "1",
      cost_metadata: null, seed: null, attempt_controls: null },
  }).evidence.references;
}

function capturedItem(path: string): CapturedItem {
  return { occurrence_id: "occ-scope" as ItemOccurrenceId, revision_id: "brief-1", path, producer_local_id: null,
    item_id_or_path: path, selected_value: ["src/a.ts"] } as unknown as CapturedItem;
}

test("reachability: restricted brief and assessment fields classify as restricted evidence", () => {
  expect(evidenceKindForCapturedPath("brief", "/files_in_scope/0")).toEqual({ ok: true, value: RESTRICTED_KIND });
  expect(evidenceKindForCapturedPath("assessment", "/test_evidence/0")).toEqual({ ok: true, value: RESTRICTED_KIND });
});

test("reachability: a captured files_in_scope item is packaged as restricted evidence", () => {
  const item = capturedItem("/files_in_scope/0");
  const kind = evidenceKindForCapturedPath("brief", item.path);
  if (!kind.ok) throw new Error(kind.error.detail);
  const packaged = capturedReference("scope", item, kind.value, item.selected_value);
  expect(packaged.ok).toBe(true);
  expect(packaged.ok && packaged.value.kind).toBe(RESTRICTED_KIND);
});

test("reachability: restricted evidence from grade-context intake is withheld on export", () => {
  expect(exported(intake(), closed).text).not.toContain(RESTRICTED);
});

test("reachability: restricted evidence from grade-context intake is exported when the target allows it", () => {
  expect(exported(intake(), allowing({ allow_restricted_content: true })).text).toContain(RESTRICTED);
});

test("semantics: restricted evidence from grade-context intake keeps its kind through export", () => {
  expect(exported(intake(), closed).reasons).toEqual([{ path: restrictedPath, reason: "restricted_content" }] as unknown as ReturnType<typeof exported>["reasons"]);
  expect(exported(intake(), allowing({ allow_restricted_content: true })).reasons).toEqual([]);
});

test("semantics: restricted content is withheld when the policy has no restricted flag", () => {
  const { text, reasons } = exported([bothKinds[0]], closed);
  expect(text).not.toContain(RESTRICTED);
  expect(reasons).toEqual([{ path: restrictedPath, reason: "restricted_content" }] as unknown as typeof reasons);
});

test("semantics: allowing repository content and raw output does not release restricted content", () => {
  const { text, reasons } = exported(bothKinds, allowing({ allow_raw_build_output: true, allow_raw_test_output: true,
    allow_repository_content: true, allow_restricted_content: false }));
  expect(text).toContain(SOURCE);
  expect(text).not.toContain(RESTRICTED);
  expect(reasons).toEqual([{ path: restrictedPath, reason: "restricted_content" }] as unknown as typeof reasons);
});

test("semantics: allow_restricted_content releases restricted content only", () => {
  const { text, reasons } = exported(bothKinds, allowing({ allow_restricted_content: true }));
  expect(text).toContain(RESTRICTED);
  expect(text).not.toContain(SOURCE);
  expect(reasons).toEqual([{ path: repositoryPath, reason: "repository_content" }]);
});

test("semantics: only the raw export credential may request allow_restricted_content", async () => {
  const app = createApp({ db: {} as Database, credentials: { ingest: [], read: [{ ...tenant, token: "read-token" }],
    export_raw: [{ ...tenant, token: "raw-token" }] } });
  const body = JSON.stringify({ target: { name: "assay", redaction_policy: { allow_restricted_content: true } } });
  const request = (token: string) => app.request("/v1/exports/assay", { method: "POST",
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" }, body });
  const read = await request("read-token");
  expect(read.status).toBe(403);
  expect(await read.json()).toEqual({ error: { code: "forbidden", message: "raw export credential required" } });
  // The raw credential passes the gate; the empty test database then fails the export itself.
  expect((await request("raw-token")).status).not.toBe(403);
});
