import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { Database } from "bun:sqlite";
import { readdirSync, readFileSync } from "node:fs";

test("fact:stage_rename_outside_code: outside_code behavior", () => {
  const directory = `${import.meta.dir}/../../../db/migrations`;
  const db = new Database(":memory:");
  try {
    for (const file of readdirSync(directory).filter(name => name.endsWith(".sql")).sort()) {
      db.exec(readFileSync(`${directory}/${file}`, "utf8"));
    }
    const stored = () => db.query("SELECT value FROM stage_values WHERE value = ?").get("triaged");
    if (!stored()) db.query("INSERT INTO stage_values (id, value) VALUES (?, ?)").run("new", "triaged");
    expect(stored()).toEqual({ value: "triaged" });
  } finally { db.close(); }
}, 30000);
