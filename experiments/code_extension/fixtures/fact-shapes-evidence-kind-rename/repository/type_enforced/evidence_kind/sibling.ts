import { vocabularyStore } from "../src/vocabulary.ts";
import { isValue } from "./types.ts";
vocabularyStore.values("evidence_kind");
export function peerGuard(value: string): boolean { return isValue(value); }
