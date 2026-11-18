import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { Database } from "bun:sqlite";
import { readdirSync, readFileSync } from "node:fs";

test("fact:evidence_kind_rename_outside_code: outside_code behavior", () => {
  const db = new Database(":memory:");
  try {
    for (const directory of ["evidence_kind", "route_permission", "stage"]) {
      for (const file of readdirSync(directory).filter(name => name.endsWith(".sql")).sort()) {
        db.exec(readFileSync(`${directory}/${file}`, "utf8"));
      }
    }
    db.query("INSERT INTO evidence_kind_values (id, value) VALUES (?, ?)").run("new", "attestation");
    expect(db.query("SELECT value FROM evidence_kind_values WHERE id = ?").get("new")).toEqual({ value: "attestation" });
  } finally { db.close(); }
}, 30000);
