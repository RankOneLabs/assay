import { vocabularyStore } from "../src/vocabulary.ts";
export const values = vocabularyStore.values("stage");
export type Stage = (typeof values)[number];
export function isValue(value: string): value is Stage {
  return (values as readonly string[]).includes(value);
}
