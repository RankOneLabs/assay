import type { RoutePermission } from "./types.ts";
import { acceptValue, enforceLimit } from "./policy.ts";
import { validateKey } from "./anchor.ts";
export function edit(key: string, value: RoutePermission, count = 1): { key: string; value: RoutePermission } {
  enforceLimit(count, 100);
  return { key: validateKey(key), value: acceptValue(value) };
}
/** Independent peer acceptance check: the operation must understand the value. */
export function peerGuard(value: string): boolean {
  switch (value) {
    case "case_read":
    case "case_write":
    case "case_admin":
      return true;
    default:
      return false;
  }
}

/** Compile-time control: every vocabulary member requires an operation. */
export const operations: Record<RoutePermission, (key: string) => string> = {
  case_read: key => `${key}:case_read`,
  case_write: key => `${key}:case_write`,
  case_admin: key => `${key}:case_admin`,
};
