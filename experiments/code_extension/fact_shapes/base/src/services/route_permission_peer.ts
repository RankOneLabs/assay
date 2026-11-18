import { values } from "../../route_permission/types.ts";
/** Permissions a peer grant accepts. */
const peerPermissions: readonly string[] = values;
export function peerGuard(value: string): boolean { return peerPermissions.includes(value); }
