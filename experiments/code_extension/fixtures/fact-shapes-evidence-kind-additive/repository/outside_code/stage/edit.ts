import type { Stage } from "./types.ts";
import { acceptValue, enforceLimit } from "./policy.ts";
import { validateKey } from "./anchor.ts";
export function edit(key: string, value: Stage, count = 1): { key: string; value: Stage } {
  enforceLimit(count, 100);
  return { key: validateKey(key), value: acceptValue(value) };
}
/** Independent peer acceptance check: the operation must understand the value. */
export function peerGuard(value: string): boolean {
  switch (value) {
    case "queued":
    case "active":
    case "complete":
      return true;
    default:
      return false;
  }
}

/** Compile-time control: every vocabulary member requires an operation. */
export const operations: Record<Stage, (key: string) => string> = {
  queued: key => `${key}:queued`,
  active: key => `${key}:active`,
  complete: key => `${key}:complete`,
};
