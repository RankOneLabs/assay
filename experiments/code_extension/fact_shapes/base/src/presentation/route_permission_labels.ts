import { values, type RoutePermission } from "../../route_permission/types.ts";
import { titleLabels } from "./labels.ts";
/** Display label for each of the route permissions. */
export const routePermissionLabels: Record<RoutePermission, string> = titleLabels(values);
export function routePermissionLabel(value: RoutePermission): string { return routePermissionLabels[value]; }
