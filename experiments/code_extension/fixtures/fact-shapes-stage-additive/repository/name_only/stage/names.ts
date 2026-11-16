import { isValue } from "./types.ts";
export const DEFAULT_ROUTE = "/jobs";
export const descriptiveRegistry: Readonly<Record<string, string>> = {
  "queued": "/jobs/queued",
  "active": "/jobs/active",
  "complete": "/jobs/complete",
};
export function routeFor(value: string): string {
  return (Object.hasOwn(descriptiveRegistry, value) ? descriptiveRegistry[value] : undefined) ?? DEFAULT_ROUTE;
}
export function validateRegisteredValue(value: string): boolean {
  return Object.hasOwn(descriptiveRegistry, value) && isValue(value);
}
