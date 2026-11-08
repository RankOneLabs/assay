import { expect, test } from "bun:test";
import { createApp } from "../../../src/http/app";
import { credentialsFromEnv, type Credential, type Credentials } from "../../../src/http/ingest-auth";
import type { Database } from "../../../src/storage/database";

const tenant = { producer: "oakridge", namespace: "alpha" };
const read = [{ ...tenant, token: "read-token" }];
const exporting = [{ ...tenant, token: "export-token" }];
const raw = [{ ...tenant, token: "raw-token" }];
/** Credentials with an export list, which the type gains only with the task. */
const withExport = (credentials: Record<string, readonly Credential[]>): Credentials => credentials as unknown as Credentials;
const exportList = (credentials: Credentials): unknown => (credentials as unknown as { export?: unknown }).export;

async function exportWith(credentials: Credentials, token: string, redaction_policy: Record<string, boolean> = {}) {
  // The 403 gate runs before any database access; past it, the empty test database fails the
  // export itself, which the app reports as a 500.
  const app = createApp({ db: {} as Database, credentials });
  const response = await app.request("/v1/exports/assay", { method: "POST",
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: JSON.stringify({ target: { name: "assay", redaction_policy } }) });
  return { status: response.status, body: await response.json() as { error?: { message?: string } } };
}

test("reachability: an export token configured in OBSERVATION_EXPORT_CREDENTIALS passes the export gate", async () => {
  const credentials = credentialsFromEnv({ OBSERVATION_READ_CREDENTIALS: JSON.stringify(read),
    OBSERVATION_EXPORT_CREDENTIALS: JSON.stringify(exporting) } as NodeJS.ProcessEnv);
  expect((await exportWith(credentials, "export-token")).status).not.toBe(403);
});

test("reachability: OBSERVATION_EXPORT_CREDENTIALS is parsed onto the credentials' export list", () => {
  const credentials = credentialsFromEnv({ OBSERVATION_EXPORT_CREDENTIALS: JSON.stringify(exporting) } as NodeJS.ProcessEnv);
  expect(exportList(credentials)).toEqual(exporting);
});

test("semantics: an unset OBSERVATION_EXPORT_CREDENTIALS gives an empty export list", () => {
  expect(exportList(credentialsFromEnv({} as NodeJS.ProcessEnv))).toEqual([]);
});

test("semantics: a malformed OBSERVATION_EXPORT_CREDENTIALS is refused", () => {
  expect(() => credentialsFromEnv({ OBSERVATION_EXPORT_CREDENTIALS: JSON.stringify([{ token: "", producer: "oakridge" }]) } as NodeJS.ProcessEnv))
    .toThrow("invalid observation credential configuration");
});

test("semantics: an export credential passes the export gate", async () => {
  expect((await exportWith(withExport({ ingest: [], read, export: exporting }), "export-token")).status).not.toBe(403);
});

test("semantics: a read credential can no longer export", async () => {
  const refused = await exportWith(withExport({ ingest: [], read, export: exporting, export_raw: raw }), "read-token");
  expect(refused.status).toBe(403);
  expect(refused.body.error?.message).toBe("export credential required");
});

test("semantics: an export credential cannot request raw allowances", async () => {
  for (const allowance of ["allow_raw_build_output", "allow_raw_test_output", "allow_repository_content"]) {
    const refused = await exportWith(withExport({ ingest: [], read, export: exporting, export_raw: raw }), "export-token", { [allowance]: true });
    expect(refused.status).toBe(403);
    expect(refused.body.error?.message).toBe("raw export credential required");
  }
});

test("semantics: the raw export credential still exports, with or without raw allowances", async () => {
  const credentials = withExport({ ingest: [], read, export: exporting, export_raw: raw });
  expect((await exportWith(credentials, "raw-token")).status).not.toBe(403);
  expect((await exportWith(credentials, "raw-token", { allow_raw_build_output: true })).status).not.toBe(403);
});

test("semantics: export tokens must be unique across every capability", () => {
  for (const other of ["OBSERVATION_INGEST_CREDENTIALS", "OBSERVATION_READ_CREDENTIALS", "OBSERVATION_EXPORT_RAW_CREDENTIALS"]) {
    expect(() => credentialsFromEnv({ [other]: JSON.stringify(exporting),
      OBSERVATION_EXPORT_CREDENTIALS: JSON.stringify(exporting) } as NodeJS.ProcessEnv)).toThrow("unique");
  }
  expect(() => credentialsFromEnv({ OBSERVATION_EXPORT_CREDENTIALS: JSON.stringify([...exporting, ...exporting]) } as NodeJS.ProcessEnv))
    .toThrow("unique");
});
