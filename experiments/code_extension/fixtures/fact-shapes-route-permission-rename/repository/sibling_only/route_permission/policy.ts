import { vocabularyStore } from "../src/vocabulary.ts";
import { isValue, type RoutePermission } from "./types.ts";
vocabularyStore.values("route_permission");
export function acceptValue(value: string): RoutePermission {
  if (!isValue(value)) throw new Error("unsupported route_permission");
  return value;
}
export function enforceLimit(count: number, limit: number): void {
  if (!Number.isInteger(count) || count < 0 || count > limit) throw new Error("limit exceeded");
}
const featureValues: readonly string[] = ["case_inspect"];
export function supportsFeature(value: string): boolean { return featureValues.includes(value); }
