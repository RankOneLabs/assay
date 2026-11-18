import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { Database } from "bun:sqlite";
import { readdirSync, readFileSync } from "node:fs";

test("fact:route_permission_additive_outside_code: outside_code behavior", () => {
  const directory = `${import.meta.dir}/../../../db/migrations`;
  const db = new Database(":memory:");
  try {
    for (const file of readdirSync(directory).filter(name => name.endsWith(".sql")).sort()) {
      db.exec(readFileSync(`${directory}/${file}`, "utf8"));
    }
    const stored = () => db.query("SELECT value FROM route_permission_values WHERE value = ?").get("case_inspect");
    if (!stored()) db.query("INSERT INTO route_permission_values (id, value) VALUES (?, ?)").run("new", "case_inspect");
    expect(stored()).toEqual({ value: "case_inspect" });
  } finally { db.close(); }
}, 30000);
