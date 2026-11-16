export type RequiredFeature = never;
import { isValue, type RoutePermission } from "./types.ts";
import { acceptValue, enforceLimit } from "./policy.ts";
import { validateKey } from "./anchor.ts";
import { vocabularyStore } from "../src/vocabulary.ts";
export function edit(key: string, value: RoutePermission, count = 1): { key: string; value: RoutePermission } {
  enforceLimit(count, 100);
  return { key: validateKey(key), value: acceptValue(value) };
}
export function peerGuard(value: string): boolean { return isValue(value); }
export const operations = vocabularyStore.record("route_permission", value => (key: string) => `${key}:${value}`);
export function requestFeature(key: string, value: RequiredFeature, count = 1): { key: string; value: RoutePermission | RequiredFeature } {
  return edit(key, value as never, count);
}
