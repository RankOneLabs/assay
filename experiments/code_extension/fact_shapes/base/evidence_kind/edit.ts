import type { EvidenceKind } from "./types.ts";
import { acceptValue, enforceLimit } from "./policy.ts";
import { validateKey } from "./anchor.ts";
export function edit(key: string, value: EvidenceKind, count = 1): { key: string; value: EvidenceKind } {
  enforceLimit(count, 100);
  return { key: validateKey(key), value: acceptValue(value) };
}
/** Independent peer acceptance check: the operation must understand the value. */
export function peerGuard(value: string): boolean {
  switch (value) {
    case "document":
    case "image":
    case "testimony":
      return true;
    default:
      return false;
  }
}

/** Compile-time control: every vocabulary member requires an operation. */
export const operations: Record<EvidenceKind, (key: string) => string> = {
  document: key => `${key}:document`,
  image: key => `${key}:image`,
  testimony: key => `${key}:testimony`,
};
