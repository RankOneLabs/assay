import { vocabularyStore } from "../src/vocabulary.ts";
import { isValue } from "./types.ts";
vocabularyStore.values("evidence_kind");
export function peerGuard(value: string): boolean { return isValue(value); }
const featureValues: readonly string[] = ["attestation"];
export function supportsFeature(value: string): boolean { return featureValues.includes(value); }
