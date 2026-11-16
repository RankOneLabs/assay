/** Canonical route_permission vocabulary. All typed readers derive from this tuple. */
export const values = Object.freeze([
  "case_read",
  "case_write",
  "case_admin"
] as const);
export type RoutePermission = (typeof values)[number];
export function isValue(value: string): value is RoutePermission {
  return (values as readonly string[]).includes(value);
}
