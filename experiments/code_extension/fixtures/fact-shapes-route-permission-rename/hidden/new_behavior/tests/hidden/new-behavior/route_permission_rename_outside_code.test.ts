import { expect, test } from "bun:test";
import { Database } from "bun:sqlite";
import { readdirSync, readFileSync } from "node:fs";

test("fact:route_permission_rename_outside_code: outside_code behavior", () => {
  const db = new Database(":memory:");
  try {
    for (const directory of ["evidence_kind", "route_permission", "stage"]) {
      for (const file of readdirSync(directory).filter(name => name.endsWith(".sql")).sort()) {
        db.exec(readFileSync(`${directory}/${file}`, "utf8"));
      }
    }
    db.query("INSERT INTO route_permission_capabilities (id, value) VALUES (?, ?)").run("new", "case_inspect");
    expect(db.query("SELECT value FROM route_permission_capabilities WHERE id = ?").get("new")).toEqual({ value: "case_inspect" });
    expect(() => db.query("INSERT INTO route_permission_capabilities (id, value) VALUES (?, ?)").run("old", "case_read")).toThrow();
  } finally { db.close(); }
});
