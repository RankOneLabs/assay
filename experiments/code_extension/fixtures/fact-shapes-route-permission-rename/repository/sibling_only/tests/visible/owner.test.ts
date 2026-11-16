import { expect, test } from "bun:test";
import { cp, mkdir, rm, readdir } from "node:fs/promises";

/** A change to the sole owner must reach every derived consumer, without edits elsewhere. */
for (const feature of ["stage", "evidence_kind", "route_permission"]) {
  for (const task of ["additive", "rename"]) {
    test(`${feature} ${task}: changing only the owner updates all derived consumers`, async () => {
      const root = `${import.meta.dir}/../..`;
      const target = `/tmp/owner-control-${crypto.randomUUID()}`;
      try {
        for (const name of ["stage", "evidence_kind", "route_permission"]) {
          await cp(`${root}/${name}`, `${target}/${name}`, { recursive: true });
        }
        await mkdir(`${target}/src`, { recursive: true });
        for (const name of ["bootstrap.ts", "vocabulary.ts"]) {
          await cp(`${root}/src/${name}`, `${target}/src/${name}`);
        }
        const migrations = (await readdir(`${target}/${feature}`)).filter(name => name.endsWith(".sql")).sort();
        const candidates = ["types.ts", "policy.ts", "names.ts", "sibling.ts", "state.ts", migrations.at(-1)!];
        const owners: string[] = [];
        for (const candidate of candidates) {
          const source = await Bun.file(`${target}/${feature}/${candidate}`).text();
          if (source.includes("vocabularyStore.define(") || /value IN \(/.test(source)) owners.push(candidate);
        }
        expect(owners.length).toBe(1);
        const path = `${target}/${feature}/${owners[0]}`;
        const original = await Bun.file(path).text();
        const sql = path.endsWith(".sql");
        const first = sql ? /value IN \('([^']+)'/.exec(original)?.[1]
          : /vocabularyStore.define\([^,]+, \["([^"]+)"/.exec(original)?.[1];
        expect(first).toBeDefined();
        const changed = task === "rename"
          ? original.replace(sql ? `'${first}'` : `"${first}"`, sql ? "'study_future'" : '"study_future"')
          : sql ? original.replace(/(value IN \([^)]*)(\))/, "$1, 'study_future'$2")
          : original.replace(/(\[[^\]]*)(\]\s*(?:as const)?\))/, '$1, "study_future"$2');
        expect(changed).not.toBe(original);
        await Bun.write(path, changed);
        await Bun.write(`${target}/probe.ts`, `
          import "./src/bootstrap.ts";
          import { edit, peerGuard, operations } from "./${feature}/edit.ts";
          import { acceptValue } from "./${feature}/policy.ts";
          import { routeFor, validateRegisteredValue } from "./${feature}/names.ts";
          import { peerGuard as peer } from "./${feature}/sibling.ts";
          import { values } from "./${feature}/types.ts";
          import { Database } from "bun:sqlite";
          if (!values.includes("study_future") || !peerGuard("study_future") || !peer("study_future")
              || !validateRegisteredValue("study_future") || acceptValue("study_future") !== "study_future"
              || edit("key", "study_future").value !== "study_future"
              || operations.study_future("key") !== "key:study_future"
              || routeFor("study_future") !== "/jobs/study_future") throw new Error("stale derived consumer");
          if (${task === "rename"} && (values.includes(${JSON.stringify(first)})
              || peer(${JSON.stringify(first)}) || validateRegisteredValue(${JSON.stringify(first)})))
            throw new Error("stale renamed value");
          using db = new Database(":memory:");
          for (const file of ${JSON.stringify(migrations)}) db.exec(await Bun.file(import.meta.dir + "/${feature}/" + file).text());
          db.query("INSERT INTO ${feature}_values VALUES (?, ?)").run("new", "study_future");
          console.log("owner mutation propagated");
        `);
        const result = Bun.spawnSync([process.execPath, `${target}/probe.ts`]);
        expect(new TextDecoder().decode(result.stderr)).toBe("");
        expect(result.exitCode).toBe(0);
        expect(new TextDecoder().decode(result.stdout)).toContain("owner mutation propagated");
      } finally { await rm(target, { recursive: true, force: true }); }
    }, 20000);
  }
}
