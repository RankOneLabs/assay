import { vocabularyStore } from "../src/vocabulary.ts";
export const values = vocabularyStore.define("route_permission", ["case_read", "case_write", "case_admin"] as const);
export type RoutePermission = (typeof values)[number];
export function isValue(value: string): value is RoutePermission {
  return (values as readonly string[]).includes(value);
}
import type { RequiredFeature } from "./edit.ts";
export const featureTypes: Record<RequiredFeature, true> & Record<string, true> = {"case_read": true};
export function supportsFeature(value: string): boolean { return Object.hasOwn(featureTypes, value); }
