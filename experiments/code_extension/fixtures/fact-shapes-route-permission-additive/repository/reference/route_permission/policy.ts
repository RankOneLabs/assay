import { isValue, type RoutePermission } from "./types.ts";
export function acceptValue(value: string): RoutePermission {
  if (!isValue(value) || !["case_read", "case_write", "case_admin"].includes(value)) throw new Error("unsupported route_permission");
  return value;
}
export function enforceLimit(count: number, limit: number): void {
  if (!Number.isInteger(count) || count < 0 || count > limit) throw new Error("limit exceeded");
}
