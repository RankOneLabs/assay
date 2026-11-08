import { expect, test } from "bun:test";
import { createHttpApp, type DefinitionApiDependencies } from "../../../src/http/app";
import { browserWritePolicy } from "../../../src/http/browser-write-policy";
import { requiresControlToken, type ServedControlPlaneAccess } from "../../../src/http/control-auth";
import { HTTP_ROUTES, matchRoute } from "../../../src/http/routes";
import { OPERATION_REGISTRY } from "../../../src/operations/registry";

const TOKEN = "secret";
const withToken: ServedControlPlaneAccess = { kind: "token_required", token: TOKEN };
/** The served app with no database or core behind it: the route never needs either. */
const httpApp = (access: ServedControlPlaneAccess = withToken) =>
  createHttpApp({ ...({} as DefinitionApiDependencies), application_version: "test", access, write_policy: browserWritePolicy([]) });
const operator = { authorization: `Bearer ${TOKEN}` };
const operations = (headers: Record<string, string> = operator, access: ServedControlPlaneAccess = withToken) =>
  httpApp(access).request("http://127.0.0.1:8790/api/operations", { headers });
const body = async (response: Response) => (await response.json()) as { operations?: { key?: unknown; error_codes?: unknown }[] };
const registered = (app: ReturnType<typeof createHttpApp>) =>
  app.routes.filter((route) => route.method !== "ALL").map((route) => `${route.method} ${route.path}`).sort();

test("reachability: an operator's GET /api/operations answers 200 with every registered operation", async () => {
  const response = await operations();
  expect({ status: response.status, keys: (await body(response)).operations?.map((operation) => operation.key) })
    .toEqual({ status: 200, keys: OPERATION_REGISTRY.map((operation) => operation.key) });
});

test("reachability: a loopback-open control plane serves it to a loopback request", async () => {
  const response = await operations({ host: "127.0.0.1:8790" }, { kind: "loopback_open" });
  expect({ status: response.status, count: (await body(response)).operations?.length }).toEqual({ status: 200, count: OPERATION_REGISTRY.length });
});

test("reachability: every registered route is classified and every classified route is registered, GET /api/operations among them", () => {
  const routes = registered(httpApp({ kind: "loopback_open" }));
  expect({ registered: routes, includes: routes.includes("GET /api/operations") })
    .toEqual({ registered: HTTP_ROUTES.map((route) => `${route.method} ${route.path}`).sort(), includes: true });
});

test("semantics: each operation lists its key, input and output schema, and error codes, in registry order", async () => {
  const response = await operations();
  expect(await response.json()).toEqual({
    operations: OPERATION_REGISTRY.map(({ key, input_schema, output_schema, error_codes }) => ({ key, input_schema, output_schema, error_codes })),
  });
});

test("semantics: an operation with no error codes lists an empty array", async () => {
  const listed = (await body(await operations())).operations?.find((operation) => operation.key === "value.publish");
  expect(listed?.error_codes).toEqual([]);
});

test("semantics: the route is classified as an operator route", () => {
  expect([matchRoute("GET", "/api/operations")?.authority, requiresControlToken("GET", "/api/operations"), requiresControlToken("HEAD", "/api/operations")])
    .toEqual(["operator", true, true]);
});

test("semantics: without the control credential the route answers 401", async () => {
  const attempts: Record<string, string>[] = [{}, { authorization: "Bearer wrong" }];
  const refused = await Promise.all(attempts.map(async (headers) => {
    const response = await operations(headers);
    return { status: response.status, code: ((await response.json()) as { code?: unknown }).code };
  }));
  expect(refused).toEqual([{ status: 401, code: "unauthorized" }, { status: 401, code: "unauthorized" }]);
});
