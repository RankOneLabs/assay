# Code examples: where the refactor lost a check

These four comparisons show the check before the refactor, the **clean
refactor** that preserves its intended behavior, and the **omitted fixture**
given to a reviewing agent. The excerpts are shortened to the relevant lines;
each source or fixture definition is linked at the pinned commit below.
Long statements are wrapped inside the code blocks; the pinned links show the
original layout. These cases have different models, denominators, and run
histories, so they are not matched arms of one experiment. For examples 2 and
3, a checked-in clean file is not evidence that the generated omitted version
kept its guard.

The study calls a session `remnant_fixed` only when the omission's hidden test
passes on the final tree while `tsc`, visible tests, and other shares' hidden
tests still pass. That measure includes repair and is not a detection rate.
The [report](./README.md) gives the results and their limits;
[Supporting data](./supporting-data.md#archives) lists the per-fixture archives.

## Example 1

**A move whose gap reads as a local diff.** Two driver units must not share a
`unit_id`. The refactor combines the old input and non-input fan-out branches
into one pass, turning their identical checks into one guard.

**Before: checked-in old `src/decision/derive.ts` (`ts`)**

```ts
const seen = new Set<string>();
if (seen.has(parsed.value.unit_id)) return err({
  kind: "malformed_driver_artifact",
  stage_key: contract.stage_key,
  artifact_id: artifact.artifact_id,
  path: spec.unit_id_path,
  detail: `duplicate unit_id '${parsed.value.unit_id}'`,
});
seen.add(parsed.value.unit_id);
if (seen.has(parsed.value.unit_id)) return err({
  kind: "malformed_driver_artifact",
  stage_key: contract.stage_key,
  artifact_id: null,
  path: spec.unit_id_path,
  detail: `duplicate unit_id '${parsed.value.unit_id}'`,
});
seen.add(parsed.value.unit_id);
```

The two guards above come from different branches; intervening lines are
omitted. The following `mint.ts` excerpts show selected emitted lines from
`_merged_fan_out`, not checked-in files.

**Clean refactor: generated `src/decision/mint.ts` (`ts`)**

```ts
const seen = new Set<string>();
for (const { item, source_artifact_id } of items) {
  const parsed = parseDriverItem(item, spec);
  if (seen.has(parsed.value.unit_id)) return err({
    kind: "malformed_driver_artifact",
    stage_key: contract.stage_key,
    artifact_id: source_artifact_id,
    path: spec.unit_id_path,
    detail: `duplicate unit_id '${parsed.value.unit_id}'`
  });
  seen.add(parsed.value.unit_id);
  driverUnits.push({ unit: parsed.value, source_artifact_id });
}
```

**Omitted fixture: generated with `omit=True` (`ts`)**

```ts
for (const { item, source_artifact_id } of items) {
  const parsed = parseDriverItem(item, spec);
  driverUnits.push({ unit: parsed.value, source_artifact_id });
}
```

**What changed.** `omit=True` drops both `const seen = new Set<string>();`
at generator line 268 and `_DUPLICATE_CHECK` at line 274; the check's text is
defined at lines 239 to 243. A search of the old file still finds the
second, identical guard at line 228, but the generated one-pass file has
neither. Neither clean nor omitted `decision/mint.ts` is checked in.

Evidence: [old branches](https://github.com/RankOneLabs/assay/blob/2589d8290b502e5d9f6cf71a07fe537241235da0/experiments/verification_pilot/raw/refactor_repo/src/decision/derive.ts#L207-L232),
[clean and omitted generator](https://github.com/RankOneLabs/assay/blob/2589d8290b502e5d9f6cf71a07fe537241235da0/experiments/verification_pilot/self_trust/refactor.py#L239-L278),
[hidden test](https://github.com/RankOneLabs/assay/blob/2589d8290b502e5d9f6cf71a07fe537241235da0/experiments/verification_pilot/self_trust/refactor.py#L413-L419).

The missing check is easy to see when the generated pass still resembles the
old branches. Fixture `S` was restored in 36 of 36 sessions across three
models, pooled with its six long-history runs
([Finding 1](./README.md#finding-1-moves-are-caught-rewrites-are-missed-at-every-size)).

## Example 2

**The same guarantee in a different shape.** Unit materialization must reject
duplicate `unit_id` values. The architectural rewrite moves that check from
a flat batch loop into `derive.ts` with separate input and non-input branches.

**Before: checked-in old `materialize-units.ts` (`ts`)**

```ts
const ids = new Set<string>();
for (const item of items) {
  const parsed = parseUnit(item, spec);
  if (!parsed.ok) return parsed;
  if (ids.has(parsed.value.unit_id)) return err({
    operation: "materialize_units",
    unit_id: parsed.value.unit_id,
    detail: "duplicate unit_id"
  });
  ids.add(parsed.value.unit_id);
  units.push(parsed.value);
}
```

**Clean refactor: checked-in `src/decision/derive.ts` (`ts`)**

```ts
const seen = new Set<string>();
if (materialization.over.from === "input") {
  for (const artifact of selectDriverArtifacts(inputs, materialization.over.input_name)) {
    if (seen.has(parsed.value.unit_id)) return err({
      kind: "malformed_driver_artifact",
      stage_key: contract.stage_key,
      artifact_id: artifact.artifact_id,
      path: spec.unit_id_path,
      detail: `duplicate unit_id '${parsed.value.unit_id}'`
    });
    seen.add(parsed.value.unit_id);
  }
} else {
  for (const item of over.value) {
    if (seen.has(parsed.value.unit_id)) return err({
      kind: "malformed_driver_artifact",
      stage_key: contract.stage_key,
      artifact_id: null,
      path: spec.unit_id_path,
      detail: `duplicate unit_id '${parsed.value.unit_id}'`
    });
    seen.add(parsed.value.unit_id);
  }
}
```

Intervening parse and error-handling lines are omitted from both branch
excerpts.

**Omitted fixture: generated `src/decision/derive.ts` (`ts`)**

```ts
const seen = new Set<string>();
if (materialization.over.from === "input") {
  for (const artifact of selectDriverArtifacts(inputs, materialization.over.input_name)) {
    seen.add(parsed.value.unit_id);
  }
} else {
  for (const item of over.value) {
    if (seen.has(parsed.value.unit_id)) return err({
      kind: "malformed_driver_artifact",
      stage_key: contract.stage_key,
      artifact_id: null,
      path: spec.unit_id_path,
      detail: `duplicate unit_id '${parsed.value.unit_id}'`
    });
    seen.add(parsed.value.unit_id);
  }
}
```

**What changed.** The fixture deletes only the driver-artifact branch's
`seen.has(...)` rejection at clean destination line 200. The non-input-binding
branch keeps its identical guard at line 211, which can make a repository
search look reassuring. `rewrite0` uses this omission A; `L1` to `L3`
inherit it but are reported on their own rows. The clean destination is
checked in; the omitted variant is generated from the omission marker.

Evidence: [old batch](https://github.com/RankOneLabs/assay/blob/2589d8290b502e5d9f6cf71a07fe537241235da0/experiments/verification_pilot/raw/rewrite_repo/before/src/compiler/materialize-units.ts#L48-L56),
[clean destination and surviving guard](https://github.com/RankOneLabs/assay/blob/2589d8290b502e5d9f6cf71a07fe537241235da0/experiments/verification_pilot/raw/rewrite_repo/after/src/decision/derive.ts#L190-L215),
[omission marker](https://github.com/RankOneLabs/assay/blob/2589d8290b502e5d9f6cf71a07fe537241235da0/experiments/verification_pilot/self_trust/rewrite.py#L73-L83),
[hidden test](https://github.com/RankOneLabs/assay/blob/2589d8290b502e5d9f6cf71a07fe537241235da0/experiments/verification_pilot/self_trust/rewrite.py#L238-L248).

A reviewer has to compare behavior across two shapes and two branches, not
just search for the guard. Fixture `rewrite0` omission A was restored in 2 of
17 sessions across the same three models as fixture `S`
([Finding 1](./README.md#finding-1-moves-are-caught-rewrites-are-missed-at-every-size)).

## Example 3

**A rewrite that kept the old checklist legible.** A final pull request
reported as merged must carry `merged_at` evidence. The `forge-rewrite`
refactor turns each old `else if` condition into a named rule with the same
explanation string.

**Before: checked-in old `final-pull-request.ts` (`ts`)**

```ts
} else if (input.observation.state === "closed_unmerged") {
  finding = pullRequestMismatch(
    "closed_without_merge",
    "pull request closed without merging into the integration branch"
  );
} else if (input.observation.state === "merged" && input.observation.merged_at === null) {
  finding = pullRequestMismatch(
    "pull_request_mismatch",
    "merged observation is missing merged_at evidence"
  );
}
```

**Clean refactor: checked-in rule list (`ts`)**

```ts
  rules.notClosedUnmerged("pull request closed without merging into the integration branch"),
  rules.mergedWithEvidence("merged observation is missing merged_at evidence"),
];
```

**Omitted fixture: generated rule list (`ts`)**

```ts
  rules.notClosedUnmerged("pull request closed without merging into the integration branch"),
];
```

The clean and omitted blocks show the trailing lines of `FINAL_RULES`;
earlier rules are excluded from both excerpts.

**What changed.** The omission removes only
`rules.mergedWithEvidence(...)` at clean destination line 100. The closing
`];` remains. The old condition and named rule carry the same explanation
string, and the sibling `cohort-pull-request.ts` retains its own
`rules.mergedWithEvidence(...)` at line 110. That surviving rule could fool a
search across the forge package. The clean rewrite is checked in; the omitted
list is generated from `FORGE_REWRITE` with `stored="clean"`.

The companion `forge-move` starts with the same old condition. Its checked-in
clean chain has the
[matching branch](https://github.com/RankOneLabs/assay/blob/2589d8290b502e5d9f6cf71a07fe537241235da0/experiments/verification_pilot/raw/forge_repo/move/src/forge/final-pull-request.ts#L136-L140);
its generated omitted variant removes the
`} else if (input.observation.state === "merged" && input.observation.merged_at === null)`
branch from that chain. Its fixture also stores the clean state.

Evidence: [old chain](https://github.com/RankOneLabs/assay/blob/2589d8290b502e5d9f6cf71a07fe537241235da0/experiments/verification_pilot/raw/forge_repo/before/src/domain/final-pull-request.ts#L136-L140),
[clean rule list](https://github.com/RankOneLabs/assay/blob/2589d8290b502e5d9f6cf71a07fe537241235da0/experiments/verification_pilot/raw/forge_repo/rewrite/src/forge/final-pull-request.ts#L93-L101),
[clean/omitted fixture definitions](https://github.com/RankOneLabs/assay/blob/2589d8290b502e5d9f6cf71a07fe537241235da0/experiments/verification_pilot/self_trust/fixtures.py#L277-L285),
[forge-move fixture definition](https://github.com/RankOneLabs/assay/blob/2589d8290b502e5d9f6cf71a07fe537241235da0/experiments/verification_pilot/self_trust/fixtures.py#L255-L266),
[sibling rule](https://github.com/RankOneLabs/assay/blob/2589d8290b502e5d9f6cf71a07fe537241235da0/experiments/verification_pilot/raw/forge_repo/rewrite/src/forge/cohort-pull-request.ts#L102-L111),
[shared hidden test](https://github.com/RankOneLabs/assay/blob/2589d8290b502e5d9f6cf71a07fe537241235da0/experiments/verification_pilot/self_trust/fixtures.py#L174-L202).

The rule list offers a one-to-one comparison even after a rewrite.
`forge-rewrite` was restored in 6 of 6 sessions on Gemini 4 Argon and 5 of 5
on Gemini 3.8 Flash. `forge-move` was restored in 6 of 6 on Argon; it has no
Flash result because both Flash runs stopped on an unbilled provider error
([Finding 2](./README.md#finding-2-what-decides-it-seems-to-be-whether-old-and-new-line-up)).

## Example 4

**A real move with a surviving but irrelevant guard.** A resumed session
must not inherit a disallowed parent model. Oakridge PR #146 moved the resume
lookup into a Claude Code adapter, where the checked-in path assigns the
parent model without filtering it.

**Before: checked-in old session handler (`ts`)**

```ts
if (typeof payload.model === "string" && isAllowedModel(payload.model)) {
  parentModel = payload.model;
}
```

**Clean refactor: from `Omission.clean` fixture definition, line 299 (`ts`)**

```ts
if (
  typeof payload.model === "string" &&
  (ALLOWED_MODELS as readonly string[]).includes(payload.model)
) model = payload.model;
```

This clean line exists as a fixture string, not as a checked-in adapter line.

**Omitted fixture: checked-in adapter (`ts`)**

```ts
if (evt.type === "session_started") {
  if (typeof payload.workdir === "string") workdir = payload.workdir;
  if (typeof payload.worktreePath === "string")
    parentWorktreePath = payload.worktreePath;
  if (typeof payload.model === "string") model = payload.model;
}
```

**Surviving legacy path: checked-in handler (`ts`)**

```ts
if (typeof payload.model === "string" && LEGACY_ALLOWED_MODELS.includes(payload.model)) {
  parentModel = payload.model;
}
```

**What changed.** `RESUME_146` declares `stored="omitted"` at fixture line
301, so the unguarded adapter is the checked-in variant. The old handler's
`LEGACY_ALLOWED_MODELS` remains declared at line 21 and applied at line 161,
but this legacy fallback does not protect the new adapter path. The adapter
itself imports `ALLOWED_MODELS` at line 18 and exposes `isAllowedModel` at
line 107; its resume assignment at line 323 never calls that predicate.
A search for either allowlist signal can therefore give false reassurance.
Oakridge PR #153 later restored the adapter guard.

The hidden test replays a resume request with a disallowed parent model and
asserts that resume either fails with 400 or returns no inherited model.
Inheriting the disallowed model is its only failing outcome.

Evidence: [old guard](https://github.com/RankOneLabs/assay/blob/2589d8290b502e5d9f6cf71a07fe537241235da0/experiments/verification_pilot/raw/resume_repo/before/core/server/handlers/sessions.ts#L150-L152),
[clean and omitted fixture definitions](https://github.com/RankOneLabs/assay/blob/2589d8290b502e5d9f6cf71a07fe537241235da0/experiments/verification_pilot/self_trust/fixtures.py#L297-L301),
[checked-in adapter path](https://github.com/RankOneLabs/assay/blob/2589d8290b502e5d9f6cf71a07fe537241235da0/experiments/verification_pilot/raw/resume_repo/after/adapters/claude-code/index.ts#L319-L324),
[adapter allowlist import](https://github.com/RankOneLabs/assay/blob/2589d8290b502e5d9f6cf71a07fe537241235da0/experiments/verification_pilot/raw/resume_repo/after/adapters/claude-code/index.ts#L18),
[adapter predicate](https://github.com/RankOneLabs/assay/blob/2589d8290b502e5d9f6cf71a07fe537241235da0/experiments/verification_pilot/raw/resume_repo/after/adapters/claude-code/index.ts#L107),
[legacy declaration](https://github.com/RankOneLabs/assay/blob/2589d8290b502e5d9f6cf71a07fe537241235da0/experiments/verification_pilot/raw/resume_repo/after/core/server/handlers/sessions.ts#L19-L23),
[legacy application](https://github.com/RankOneLabs/assay/blob/2589d8290b502e5d9f6cf71a07fe537241235da0/experiments/verification_pilot/raw/resume_repo/after/core/server/handlers/sessions.ts#L161-L163),
[hidden test](https://github.com/RankOneLabs/assay/blob/2589d8290b502e5d9f6cf71a07fe537241235da0/experiments/verification_pilot/self_trust/fixtures.py#L204-L247).

The findable guards did not protect the path that ran. Fixture `resume146`
was restored in 0 of 12 sessions across Gemini 4 Argon and Gemini 3.8 Flash;
10 of 12 submitted "complete"
([Finding 2](./README.md#finding-2-what-decides-it-seems-to-be-whether-old-and-new-line-up)).
