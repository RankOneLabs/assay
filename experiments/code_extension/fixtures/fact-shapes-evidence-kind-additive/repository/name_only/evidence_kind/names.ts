import { isValue } from "./types.ts";
export const DEFAULT_ROUTE = "/jobs";
export const descriptiveRegistry: Readonly<Record<string, string>> = {
  "document": "/jobs/document",
  "image": "/jobs/image",
  "testimony": "/jobs/testimony",
};
export function routeFor(value: string): string {
  return (Object.hasOwn(descriptiveRegistry, value) ? descriptiveRegistry[value] : undefined) ?? DEFAULT_ROUTE;
}
export function validateRegisteredValue(value: string): boolean {
  return Object.hasOwn(descriptiveRegistry, value) && isValue(value);
}
