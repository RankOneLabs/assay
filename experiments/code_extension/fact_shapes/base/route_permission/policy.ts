import { values, type RoutePermission } from "./types.ts";
/** Permissions that edit() accepts. */
const acceptedPermissions: readonly string[] = values;
export function acceptValue(value: string): RoutePermission {
  if (!acceptedPermissions.includes(value)) throw new Error("unsupported route_permission");
  return value as RoutePermission;
}
export function enforceLimit(count: number, limit: number): void {
  if (!Number.isInteger(count) || count < 0 || count > limit) throw new Error("limit exceeded");
}
