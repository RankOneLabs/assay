import { vocabularyStore } from "../src/vocabulary.ts";
export const values = vocabularyStore.values("evidence_kind");
export type EvidenceKind = (typeof values)[number];
export function isValue(value: string): value is EvidenceKind {
  return (values as readonly string[]).includes(value);
}
