import { values, type EvidenceKind } from "./types.ts";
/** Kinds that edit() accepts. */
const acceptedKinds: readonly string[] = values;
export function acceptValue(value: string): EvidenceKind {
  if (!acceptedKinds.includes(value)) throw new Error("unsupported evidence_kind");
  return value as EvidenceKind;
}
export function enforceLimit(count: number, limit: number): void {
  if (!Number.isInteger(count) || count < 0 || count > limit) throw new Error("limit exceeded");
}
