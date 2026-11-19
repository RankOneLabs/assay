import * as types from "./types.ts";
/** Permissions that edit() accepts. */
const acceptedPermissions: readonly string[] = types.values;
export function acceptValue(value: string): types.RoutePermission {
  if (!acceptedPermissions.includes(value)) throw new Error("unsupported route_permission");
  return value as types.RoutePermission;
}
export function enforceLimit(count: number, limit: number): void {
  if (!Number.isInteger(count) || count < 0 || count > limit) throw new Error("limit exceeded");
}
