export const values = ["document", "image", "testimony"] as const;
export type EvidenceKind = (typeof values)[number];
export function isValue(value: string): value is EvidenceKind {
  return (values as readonly string[]).includes(value);
}
