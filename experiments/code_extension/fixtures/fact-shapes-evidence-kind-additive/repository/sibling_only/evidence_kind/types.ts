import { vocabularyStore } from "../src/vocabulary.ts";
export const values = vocabularyStore.define("evidence_kind", ["document", "image", "testimony"] as const);
export type EvidenceKind = (typeof values)[number];
export function isValue(value: string): value is EvidenceKind {
  return (values as readonly string[]).includes(value);
}
import type { RequiredFeature } from "./edit.ts";
export const featureTypes: Record<RequiredFeature, true> & Record<string, true> = {"document": true, "attestation": true};
export function supportsFeature(value: string): boolean { return Object.hasOwn(featureTypes, value); }
