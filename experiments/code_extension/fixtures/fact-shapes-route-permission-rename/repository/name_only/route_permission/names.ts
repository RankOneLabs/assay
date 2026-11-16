import { isValue } from "./types.ts";
export const DEFAULT_ROUTE = "/jobs";
export const descriptiveRegistry: Readonly<Record<string, string>> = {
  "case_read": "/jobs/case_read",
  "case_write": "/jobs/case_write",
  "case_admin": "/jobs/case_admin",
};
export function routeFor(value: string): string {
  return (Object.hasOwn(descriptiveRegistry, value) ? descriptiveRegistry[value] : undefined) ?? DEFAULT_ROUTE;
}
export function validateRegisteredValue(value: string): boolean {
  return Object.hasOwn(descriptiveRegistry, value) && isValue(value);
}
