/** Load all candidate modules. Dependency direction keeps owners unimported by edit.ts. */
import "../stage/types.ts";
import "../stage/policy.ts";
import "../stage/names.ts";
import "../stage/sibling.ts";
import "../stage/state.ts";
import "../evidence_kind/types.ts";
import "../evidence_kind/policy.ts";
import "../evidence_kind/names.ts";
import "../evidence_kind/sibling.ts";
import "../evidence_kind/state.ts";
import "../route_permission/types.ts";
import "../route_permission/policy.ts";
import "../route_permission/names.ts";
import "../route_permission/sibling.ts";
import "../route_permission/state.ts";
import { vocabularyStore } from "./vocabulary.ts";
import sql0 from "../stage/001_constraint.sql" with { type: "text" };
vocabularyStore.constraint("stage", sql0);
import sql1 from "../evidence_kind/001_constraint.sql" with { type: "text" };
vocabularyStore.constraint("evidence_kind", sql1);
import sql2 from "../route_permission/001_constraint.sql" with { type: "text" };
vocabularyStore.constraint("route_permission", sql2);
for (const feature of ["stage", "evidence_kind", "route_permission"]) {
  if (!vocabularyStore.values(feature).length) throw new Error(`missing vocabulary owner: ${feature}`);
}
