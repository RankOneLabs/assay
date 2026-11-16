import { vocabularyStore } from "../src/vocabulary.ts";
export const values = vocabularyStore.define("evidence_kind", ["document", "image", "testimony"] as const);
export type EvidenceKind = (typeof values)[number];
export function isValue(value: string): value is EvidenceKind {
  return (values as readonly string[]).includes(value);
}
