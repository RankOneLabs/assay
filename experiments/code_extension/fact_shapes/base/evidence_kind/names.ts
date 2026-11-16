import { values, isValue } from "./types.ts";
export const DEFAULT_ROUTE = "/jobs";
export const descriptiveRegistry: Readonly<Record<string, string>> = Object.fromEntries(
  values.map(value => [value, `/jobs/${value}`]),
);
export function routeFor(value: string): string {
  return (Object.hasOwn(descriptiveRegistry, value) ? descriptiveRegistry[value] : undefined) ?? DEFAULT_ROUTE;
}
export function validateRegisteredValue(value: string): boolean {
  return isValue(value);
}
