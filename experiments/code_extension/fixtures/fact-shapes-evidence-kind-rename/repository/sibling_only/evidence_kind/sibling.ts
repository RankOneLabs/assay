import { vocabularyStore } from "../src/vocabulary.ts";
import { isValue } from "./types.ts";
vocabularyStore.define("evidence_kind", ["document", "image", "testimony"]);
export function peerGuard(value: string): boolean { return isValue(value); }
