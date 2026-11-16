import { isValue, type EvidenceKind } from "./types.ts";
export function acceptValue(value: string): EvidenceKind {
  if (!isValue(value) || !["document", "image", "testimony"].includes(value)) throw new Error("unsupported evidence_kind");
  return value;
}
export function enforceLimit(count: number, limit: number): void {
  if (!Number.isInteger(count) || count < 0 || count > limit) throw new Error("limit exceeded");
}
