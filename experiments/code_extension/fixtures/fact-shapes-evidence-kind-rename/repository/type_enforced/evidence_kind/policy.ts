import { vocabularyStore } from "../src/vocabulary.ts";
import { isValue, type EvidenceKind } from "./types.ts";
vocabularyStore.values("evidence_kind");
export function acceptValue(value: string): EvidenceKind {
  if (!isValue(value)) throw new Error("unsupported evidence_kind");
  return value;
}
export function enforceLimit(count: number, limit: number): void {
  if (!Number.isInteger(count) || count < 0 || count > limit) throw new Error("limit exceeded");
}
const featureValues: readonly string[] = ["attestation"];
export function supportsFeature(value: string): boolean { return featureValues.includes(value); }
