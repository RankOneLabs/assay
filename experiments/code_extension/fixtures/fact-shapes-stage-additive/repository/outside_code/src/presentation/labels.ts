import * as stageTypes from "../../stage/types.ts";
import * as kindTypes from "../../evidence_kind/types.ts";
import * as permissionTypes from "../../route_permission/types.ts";

/** Sentence-case display labels for snake_case names. */
export function titleLabels<const T extends readonly string[]>(names: T): Record<T[number], string> {
  return Object.fromEntries(names.map(name =>
    [name, name.charAt(0).toUpperCase() + name.slice(1).replaceAll("_", " ")],
  )) as Record<T[number], string>;
}

/** Display label for every value, used by reports. */
export const stageLabels: Record<stageTypes.Stage, string> = titleLabels(stageTypes.values);
export const evidenceKindLabels: Record<kindTypes.EvidenceKind, string> = titleLabels(kindTypes.values);
export const routePermissionLabels: Record<permissionTypes.RoutePermission, string> = titleLabels(permissionTypes.values);

export function stageLabel(value: stageTypes.Stage): string { return stageLabels[value]; }
export function evidenceKindLabel(value: kindTypes.EvidenceKind): string { return evidenceKindLabels[value]; }
export function routePermissionLabel(value: permissionTypes.RoutePermission): string {
  return routePermissionLabels[value];
}
