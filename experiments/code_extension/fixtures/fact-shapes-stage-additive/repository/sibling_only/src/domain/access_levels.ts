import { values as permissions, type RoutePermission } from "../../route_permission/types.ts";

/**
 * Route permissions are declared from least to most privileged: read, write, then
 * administration. Features that only need to see a project's records ask for the
 * least privileged one rather than spelling it out.
 */
export const readAccess: RoutePermission = permissions[0];
