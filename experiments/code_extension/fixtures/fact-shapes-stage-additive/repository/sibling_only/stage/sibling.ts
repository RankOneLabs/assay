import { vocabularyStore } from "../src/vocabulary.ts";
import { isValue } from "./types.ts";
vocabularyStore.define("stage", ["queued", "active", "complete"]);
export function peerGuard(value: string): boolean { return isValue(value); }
