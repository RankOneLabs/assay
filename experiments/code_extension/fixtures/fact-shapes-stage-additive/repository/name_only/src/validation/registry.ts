import * as stageTypes from "../../stage/types.ts";
import * as kindTypes from "../../evidence_kind/types.ts";
import * as permissionTypes from "../../route_permission/types.ts";

/** Registered values and their routes, checked by request validation. */
const registeredStages: readonly string[] = ["queued", "active", "complete"];
const registeredKinds: readonly string[] = kindTypes.values;
const registeredPermissions: readonly string[] = permissionTypes.values;

export const DEFAULT_ROUTE = "/jobs";
function routes(registered: readonly string[]): Readonly<Record<string, string>> {
  return Object.freeze(Object.fromEntries(registered.map(value => [value, `/jobs/${value}`])));
}
export const descriptiveRegistry = {
  stage: routes(registeredStages),
  evidence_kind: routes(registeredKinds),
  route_permission: routes(registeredPermissions),
} as const;
export type RegistryName = keyof typeof descriptiveRegistry;

export function routeFor(registry: RegistryName, value: string): string {
  const entries = descriptiveRegistry[registry];
  return (Object.hasOwn(entries, value) ? entries[value] : undefined) ?? DEFAULT_ROUTE;
}
export function validateRegisteredStage(value: string): value is stageTypes.Stage {
  return registeredStages.includes(value);
}
export function validateRegisteredKind(value: string): value is kindTypes.EvidenceKind {
  return registeredKinds.includes(value);
}
export function validateRegisteredPermission(value: string): value is permissionTypes.RoutePermission {
  return registeredPermissions.includes(value);
}
