import { values, type EvidenceKind } from "../../evidence_kind/types.ts";
/**
 * Kinds whose saved default follows the current selection. A default of any
 * other value is pinned when it is saved and is kept when the selection is cleared.
 */
const currentSelectionKinds: readonly string[] = values;
export class StoredEvidenceKind {
  private readonly evidence_kindSelections = new Map<string, EvidenceKind>();
  private readonly pinnedSelections = new Map<string, EvidenceKind>();
  set(key: string, value: EvidenceKind): void {
    this.evidence_kindSelections.set(key, value);
    if (currentSelectionKinds.includes(value)) this.pinnedSelections.delete(key);
    else this.pinnedSelections.set(key, value);
  }
  get(key: string): EvidenceKind | undefined {
    return this.pinnedSelections.get(key) ?? this.evidence_kindSelections.get(key);
  }
  remove(key: string): void { this.evidence_kindSelections.delete(key); }
}
