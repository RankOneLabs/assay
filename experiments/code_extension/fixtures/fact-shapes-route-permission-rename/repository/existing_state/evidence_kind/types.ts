/** Canonical evidence_kind vocabulary. All typed readers derive from this tuple. */
export const values = ["document", "image", "testimony"] as const;
export type EvidenceKind = (typeof values)[number];
export function isValue(value: string): value is EvidenceKind {
  return (values as readonly string[]).includes(value);
}
