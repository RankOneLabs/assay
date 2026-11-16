import { vocabularyStore } from "../src/vocabulary.ts";
export const values = vocabularyStore.values("route_permission");
export type RoutePermission = (typeof values)[number];
export function isValue(value: string): value is RoutePermission {
  return (values as readonly string[]).includes(value);
}
