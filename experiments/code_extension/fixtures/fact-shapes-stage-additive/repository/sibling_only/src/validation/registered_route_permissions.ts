import { values } from "../../route_permission/types.ts";
/** Routes for the registered route permissions; request validation checks membership here. */
const registeredPermissions: readonly string[] = values;
export const DEFAULT_ROUTE = "/jobs";
export const descriptiveRegistry: Readonly<Record<string, string>> = Object.freeze(
  Object.fromEntries(registeredPermissions.map(value => [value, `/jobs/${value}`])),
);
export function routeFor(value: string): string {
  return (Object.hasOwn(descriptiveRegistry, value) ? descriptiveRegistry[value] : undefined) ?? DEFAULT_ROUTE;
}
export function validateRegisteredValue(value: string): boolean { return registeredPermissions.includes(value); }
