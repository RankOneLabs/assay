import { values, type EvidenceKind } from "../../evidence_kind/types.ts";
import { titleLabels } from "./labels.ts";
/** Display label for each of the evidence kinds. */
export const evidenceKindLabels: Record<EvidenceKind, string> = titleLabels(values);
export function evidenceKindLabel(value: EvidenceKind): string { return evidenceKindLabels[value]; }
