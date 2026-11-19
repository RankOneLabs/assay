import * as types from "./types.ts";
/** Kinds that edit() accepts. */
const acceptedKinds: readonly string[] = types.values;
export function acceptValue(value: string): types.EvidenceKind {
  if (!acceptedKinds.includes(value)) throw new Error("unsupported evidence_kind");
  return value as types.EvidenceKind;
}
export function enforceLimit(count: number, limit: number): void {
  if (!Number.isInteger(count) || count < 0 || count > limit) throw new Error("limit exceeded");
}
