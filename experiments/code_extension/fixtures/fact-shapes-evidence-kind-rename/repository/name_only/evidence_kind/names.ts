import { vocabularyStore } from "../src/vocabulary.ts";
import { isValue } from "./types.ts";
vocabularyStore.values("evidence_kind");
export const DEFAULT_ROUTE = "/jobs";
export const descriptiveRegistry: Readonly<Record<string, string>> = vocabularyStore.record(
  "evidence_kind", value => `/jobs/${value}`,
);
export function routeFor(value: string): string {
  return (Object.hasOwn(descriptiveRegistry, value) ? descriptiveRegistry[value] : undefined) ?? DEFAULT_ROUTE;
}
export function validateRegisteredValue(value: string): boolean { return isValue(value); }
const featureValues: readonly string[] = ["document"];
export function supportsFeature(value: string): boolean { return featureValues.includes(value); }
