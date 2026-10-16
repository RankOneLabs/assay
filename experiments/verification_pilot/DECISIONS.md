# Verification pilot fixture decisions

## 7.1 selection, recorded before generator implementation

Read 7.1's “stay off every Part 2 anchor” at symbol level: no migration renames
readJsonPointer. This is the chosen reading of 7.1. The pinned slice has
`readJsonPointer` uses in fewer than six using files, so it cannot enter the
eligible population. The file-level reading would leave too few migrations.

The source is the committed 62-file `workflow_edit/fixtures/smoke-edit/repository`
tree, adapted from oakridge-dbos commit
`f3b3ffca43e43672ff2f58ab797d65c7532aaed8`. The source-tree commit in
this repository is `a20f94dd19c5b5d29939f4ed34a650a6d7368908`.
It contains 348,936 UTF-8 bytes and its `workflow_tree_digest` is
`sha256:a4039feafdf6061711fc040281108a65076fbbd1cfa8d3aacaac935374c6cfca`.
The pilot copies this tree without widening the wf-13 boundary.

I scanned `src/**/*.ts` for exported `const`, `function`, `type`, `interface`,
`class`, and `enum` declarations, then scanned all 62 fixture files for
identifier-boundary occurrences. The preliminary scan counted 14 eligible
exports; a broad token scan counts 16 because it includes generic names whose
occurrences are not all references to the declaration. Object keys were scanned
separately as property declarations and JSON keys. The following four have at
least six intended use occurrences in at least six distinct using files:

| old → new | kind and defining module | intended uses | using files | top-level directories |
| --- | --- | ---: | ---: | ---: |
| `JsonValue` → `PilotJsonValue` | type, `src/domain/primitives.ts` | 94 | 21 | 4 |
| `StageInstanceId` → `PilotStageInstanceId` | type, `src/domain/primitives.ts` | 78 | 19 | 4 |
| `ok` → `pilotOk` | callable value, `src/domain/primitives.ts` | 41 | 8 | 5 |
| `slot_bindings` → `pilot_slot_bindings` | object key, `src/domain/delegated-session.ts` | 29 | 9 | 6 |

Use counts exclude the defining declaration and include other uses in the
defining file. Using-file counts exclude the defining file. The value row
counts callable references and named imports, excluding `Result.ok` fields.
`slot_bindings` includes both JSON definition files and the TypeScript contract,
schema, seed, resolver, and visible tests. This key widens the kind and directory
spread. The exact use-site path lists live in `migrations.py`.

**Limitation:** 11 of the 14 exports in the preliminary eligible pool are
defined in `src/domain/primitives.ts`. The selected migrations therefore
measure ownership effects on widely used symbols from one or two modules,
not migrations generally. The ownership rotation prevents any using directory
from receiving the same ownership group in all four migrations; it cannot
create defining-module diversity absent from the slice.

## Deferred Part 2 check

The Part 2 anchor list is not in this repository. The committed sample
`assay-fixture-manifest/0.2.0` document exercises only path overlap among
`included_paths`, `excluded_paths`, and `FixtureTask.treatment_sites[].path`.
The test remains skipped until the 2b population is frozen. `DoseSite.symbol`
is the caller being treated, not the delegated-to anchor, so this manifest
cannot establish symbol-level overlap.

## Study wiring and capacity

Rotation is a subject attribute. The 16 migration/location base cases are
rendered in three block orders, giving 48 subject digests, two Tier 1 arms,
one worker repeat, and 96 cells per model. This removes within-cell sampling
repeats. Remaining variance is between subjects. The brief's phrase “per
subject, aggregated over the three rotations” now means 48 paired observations
for H1 and H2, increasing the reported n from 16 to 48. The same subject and
arm pair always has one realization, so `ExecutionOutcome.consistent_status`
can bind every input to the plan.

The snapshot declares Tier 1, Tier 2, and Tier 3 arms together. The Tier 1
plan excludes all Tier 2 and Tier 3 pairs and binds the final capacity ceiling
of 288 cells / 345,600 seconds / one active worker. A later shard changes only
its exclusions or population to retain the 0.3.0 report fingerprint. On-policy
generation remains outside the cell runtime. The local Tier 2 generation probe
used `json_value` at rotation 0, one assigned location in each of four
ownership groups, on `qwen-coder-32b` via Smithers. Each generator started
from the otherwise complete rename with one old spelling in its share. It
made four generation attempts, of which three submitted blocks, and
**discarded 4/4 attempts (100%)**: groups A, B, and D submitted but left the old
spelling in their shares; group C hit `turn_tool_call_limit`. All three
submitted candidates passed 86 Bun tests after the pinned fixture dependencies
were installed; no candidate edited outside its share. The generated block
titles were “Attempt to repair JsonValue spelling” (A and B) and “Fix JsonValue
Typo in dev-flow-stage-contracts.test.ts” (D). Their trajectory hashes were,
respectively, `sha256:963a17734b1940a469f8009c92502c6ac87509e7a36aea6ecc1a070beb5a350e`,
`sha256:bae657eb6647cc6be20835e0cbfa081d8f09ae24c76a656157f60e6eb10bc6bb`,
and `sha256:6ea0bd2eb218f7b162701f2f55cdeb791a23ce351d8c922914c35867ffdb652f`.
This is a measured local discard rate, but the observed acceptance count of
zero gives no viable Tier 2 supply estimate.

No OpenRouter credential is present in this build environment, so the paid
route's discard rate and capacity estimate cannot be reported as observed.
The 288-cell ceiling is the conservative full-grid bound pending that
measurement, and the missing rate is an explicit gate before Tier 2 cells.
The frontier model and paid dollar budget
are owned with `vp-frontier-route`; if that route is dropped, the pilot ships
single-model and excludes the frontier arm alongside deferred tiers.

The T1 repository-wide search threshold and the per-route hand-review gate
were precommitted in `SMOKE.md` before any live cell. H1 is reported separately
per model, and a local route that fails the gate is excluded from interpretation.
