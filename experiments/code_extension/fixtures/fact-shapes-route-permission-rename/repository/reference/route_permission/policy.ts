import { vocabularyStore } from "../src/vocabulary.ts";
import { isValue, type RoutePermission } from "./types.ts";
vocabularyStore.define("route_permission", ["case_read", "case_write", "case_admin"]);
export function acceptValue(value: string): RoutePermission {
  if (!isValue(value)) throw new Error("unsupported route_permission");
  return value;
}
export function enforceLimit(count: number, limit: number): void {
  if (!Number.isInteger(count) || count < 0 || count > limit) throw new Error("limit exceeded");
}
