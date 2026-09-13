export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type Issue = { code: string; message: string; ref: string | null; coordinate_id: string | null };
export type CellStatus = "succeeded" | "failed" | "missing" | "excluded" | "invalid" | "conflicted";
export type EvaluationStatus = "succeeded" | "failed" | "missing" | "invalid" | "conflicted";

export interface CostView {
  coverage: "measured" | "estimated" | "unavailable" | "mixed";
  coverage_counts: Record<string, number>;
  amounts: Record<string, number>;
  by_stage_arm: Record<string, Json>;
  attempts: number;
  expected_attempts: number | null;
  unaccounted_attempts: number | null;
  partial: boolean;
  issues: Issue[];
}

export interface RunSummary {
  run_key: string; run_id: string; manifest_ref: string | null; plan_ref: string;
  snapshot_ref: string | null; status: "complete" | "incomplete" | "unmanifested";
  subjects: number | null; arms: string[] | null; worker_repeats: number | null;
  concurrency: number | null; jig_revision: string | null; assay_version: string | null;
  started_at: string | null; completed_at: string | null; cells_total: number | null;
  cells_succeeded: number; cells_failed: number; cells_missing: number | null;
  cells_invalid: number; cells_conflicted: number; evaluations_total: number | null;
  evaluations_succeeded: number; evaluations_failed: number; evaluations_missing: number | null;
  evaluations_invalid: number; evaluations_conflicted: number;
  exclusions: ExclusionView[]; cost: CostView; issues: Issue[];
}

export interface ReportSummary {
  report_ref: string; config_ref: string; metric: "scalar" | "ordinal" | "classification";
  evaluator_id: string; reference_arm: string | null; candidates: string[] | null;
  engine_version: string | null; recomputable: boolean; recompute_disabled_reason: string | null;
  manifest_refs: string[]; issues: Issue[];
}

export interface StoreSummary { root: string | null; runs: RunSummary[]; reports: ReportSummary[]; issues: Issue[] }
export interface SubjectView { id: string; label: string; digest: string; partition: string }
export interface ArmView { id: string; worker_id: string; worker_version: string; intervention_keys: string[] }
export interface EvaluatorView { id: string; identity: Record<string, Json>; repeats: number; categories: string[] | null }
export interface ExclusionView { subject_id: string; arm_id: string; classification: string; reason: string; manifest_ref: string | null }
export interface VerdictSummary {
  evaluator_id: string; values: (string | number | null)[]; repeat_statuses: EvaluationStatus[];
  failures: string[]; agreed: boolean | null; categories: string[] | null;
}
export interface CellSummary {
  cell_id: string; subject_id: string; arm_id: string; worker_repeat: number; status: CellStatus;
  error_type: string | null; error_message: string | null; record_refs: string[];
  exclusion: ExclusionView | null; verdicts: VerdictSummary[]; issues: Issue[];
}
export interface RunDetail {
  summary: RunSummary; subjects: SubjectView[]; arms: ArmView[]; evaluators: EvaluatorView[];
  cells: CellSummary[]; missing_coordinates: string[] | null;
  cost_estimate: { amount: number | null; currency: string | null; coverage: string } | null;
}
export interface ObjectPreview { ref: string; kind: "json" | "text" | "binary" | "unavailable"; text: string | null; size_bytes: number | null; truncated: boolean; issues: Issue[] }
export interface InputView { kind: "consistency" | "generic" | "unavailable"; instruction: string | null; files: Record<string, string> | null; artifact: ObjectPreview | null }
export interface EvaluationView {
  run_key: string; cell_id: string; coordinate_id: string; evaluator_id: string; evaluator_repeat: number;
  status: EvaluationStatus; record_refs: string[]; verdict: string | number | null; reason_codes: string[];
  error_type: string | null; error_message: string | null; detail_refs: string[]; detail: Json; issues: Issue[];
}
export interface CellDetail {
  summary: CellSummary; input_ref: string | null; input_preview: InputView; output_ref: string | null;
  output_text: string | null; output_preview: ObjectPreview | null; trace_ref: string | null;
  trace_preview: ObjectPreview | null; recorded_prompt: string | null; recorded_prompt_ref: string | null;
  evaluations: EvaluationView[]; started_at: string | null; completed_at: string | null;
}
export interface DiffView { left_ref: string | null; right_ref: string | null; left_text: string | null; right_text: string | null; unified: string | null; unavailable_reason: string | null }
export interface PairView {
  run_key: string; subject_id: string; subject_label: string | null; reference_arm: string; candidate_arm: string;
  reference_cells: CellDetail[]; candidate_cells: CellDetail[]; treatment_diff: DiffView;
  output_diffs: DiffView[]; issues: Issue[];
}
export interface ComparisonView { kind: "numeric" | "ordinal" | "classification" | "unknown"; reference: string; candidate: string; values: Record<string, Json> }
export interface ReportDetail {
  summary: ReportSummary; report: Record<string, Json>; comparisons: ComparisonView[];
  missingness: Record<string, Json>; exclusions: ExclusionView[]; costs: CostView; subject_labels: Record<string, string>;
}
export interface RecomputeResult { status: "matched" | "mismatched" | "unsupported" | "failed"; matched: boolean | null; stored_digest: string; recomputed_digest: string | null; reason: string | null }
export interface ExportData {
  schema_version: "assay-review-export/0.1.0"; root_ref: string; store: StoreSummary;
  views: Record<string, Json>; objects: Record<string, Json>; capabilities: Record<string, boolean>;
}

export type Ambiguity = EvaluationView;
