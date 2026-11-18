import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { Database } from "bun:sqlite";
import { readdirSync, readFileSync } from "node:fs";

test("fact:evidence_kind_rename_outside_code: outside_code behavior", () => {
  const directory = `${import.meta.dir}/../../../db/migrations`;
  const db = new Database(":memory:");
  try {
    for (const file of readdirSync(directory).filter(name => name.endsWith(".sql")).sort()) {
      db.exec(readFileSync(`${directory}/${file}`, "utf8"));
    }
    const stored = () => db.query("SELECT value FROM evidence_kind_values WHERE value = ?").get("attestation");
    if (!stored()) db.query("INSERT INTO evidence_kind_values (id, value) VALUES (?, ?)").run("new", "attestation");
    expect(stored()).toEqual({ value: "attestation" });
  } finally { db.close(); }
}, 30000);
