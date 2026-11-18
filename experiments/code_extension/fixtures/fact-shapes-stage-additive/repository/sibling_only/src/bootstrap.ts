/** Refuse to start with an empty or repeated feature vocabulary. */
import { vocabularyStore } from "./vocabulary.ts";
for (const feature of ["stage", "evidence_kind", "route_permission"]) {
  const values = vocabularyStore.values(feature);
  if (!values.length || new Set(values).size !== values.length) {
    throw new Error(`invalid vocabulary: ${feature}`);
  }
}
