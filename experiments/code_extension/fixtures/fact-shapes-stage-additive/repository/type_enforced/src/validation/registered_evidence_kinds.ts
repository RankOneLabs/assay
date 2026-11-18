import { values } from "../../evidence_kind/types.ts";
/** Routes for the registered evidence kinds; request validation checks membership here. */
const registeredKinds: readonly string[] = values;
export const DEFAULT_ROUTE = "/jobs";
export const descriptiveRegistry: Readonly<Record<string, string>> = Object.freeze(
  Object.fromEntries(registeredKinds.map(value => [value, `/jobs/${value}`])),
);
export function routeFor(value: string): string {
  return (Object.hasOwn(descriptiveRegistry, value) ? descriptiveRegistry[value] : undefined) ?? DEFAULT_ROUTE;
}
export function validateRegisteredValue(value: string): boolean { return registeredKinds.includes(value); }
