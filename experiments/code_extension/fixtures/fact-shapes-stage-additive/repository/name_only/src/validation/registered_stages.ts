/** Routes for the registered stages; request validation checks membership here. */
const registeredStages: readonly string[] = ["queued", "active", "complete"];
export const DEFAULT_ROUTE = "/jobs";
export const descriptiveRegistry: Readonly<Record<string, string>> = Object.freeze(
  Object.fromEntries(registeredStages.map(value => [value, `/jobs/${value}`])),
);
export function routeFor(value: string): string {
  return (Object.hasOwn(descriptiveRegistry, value) ? descriptiveRegistry[value] : undefined) ?? DEFAULT_ROUTE;
}
export function validateRegisteredValue(value: string): boolean { return registeredStages.includes(value); }
