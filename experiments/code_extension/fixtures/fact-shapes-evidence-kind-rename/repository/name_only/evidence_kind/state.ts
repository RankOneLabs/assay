import { vocabularyStore } from "../src/vocabulary.ts";
vocabularyStore.values("evidence_kind");
import type { EvidenceKind } from "./types.ts";
export class StoredEvidenceKind {
  private readonly evidence_kindSelections = new Map<string, EvidenceKind>();
  set(key: string, value: EvidenceKind): void { this.evidence_kindSelections.set(key, value); }
  get(key: string): EvidenceKind | undefined { return this.evidence_kindSelections.get(key); }
  remove(key: string): void { this.evidence_kindSelections.delete(key); }
}
