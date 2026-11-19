import * as stageTypes from "../../stage/types.ts";
import * as kindTypes from "../../evidence_kind/types.ts";
import * as permissionTypes from "../../route_permission/types.ts";

/** What the peer operations accept: transitions, attachments and grants. */
const peerStages: readonly string[] = ["queued", "active", "complete"];
const peerKinds: readonly string[] = kindTypes.values;
const peerPermissions: readonly string[] = permissionTypes.values;

export function acceptsPeerStage(value: string): value is stageTypes.Stage {
  return peerStages.includes(value);
}
export function acceptsPeerKind(value: string): value is kindTypes.EvidenceKind {
  return peerKinds.includes(value);
}
export function acceptsPeerPermission(value: string): value is permissionTypes.RoutePermission {
  return peerPermissions.includes(value);
}
