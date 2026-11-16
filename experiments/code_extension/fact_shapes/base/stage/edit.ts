import type { Stage } from "./types.ts";
import { acceptValue, enforceLimit } from "./policy.ts";
import { validateKey } from "./anchor.ts";
export function edit(key: string, value: Stage, count = 1): { key: string; value: Stage } {
  enforceLimit(count, 100);
  return { key: validateKey(key), value: acceptValue(value) };
}
export function peerGuard(value: string): boolean {
  return value.length > 0 && value.length <= 80 && !value.includes("/");
}
