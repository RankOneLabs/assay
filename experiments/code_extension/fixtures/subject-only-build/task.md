# Add a subject_only evidence build

Some questions are about one captured item on its own, such as "is this plan criterion
actionable?". They can't be packaged today. `linked_sources` excludes a subject that declares
no links (as `uncited` or `unlinked`), and the other builds each serve one fixed question shape.
Add a fourth build, `subject_only`, that packages each supported subject item alone, using only
its subject slots.

A question pins the new build in its slot recipe (`input_recipe`), the same way the existing
builds are pinned:

```json
{ "recipe_version": "v1",
  "build": { "kind": "subject_only" },
  "subject": { "artifact_kind": "plan", "item_kind": "criterion" },
  "input": [],
  "output": [{ "role": "plan_criterion", "source": { "from": "subject" }, "min_count": 1, "max_count": 1 }] }
```

The build has no other fields. The required behavior:

- **Supported question.** `runPackages` accepts a question that pins
  `build: { kind: "subject_only" }`.
- **Only subject slots.** Every slot of a `subject_only` pin, input and output, must have
  `source: { from: "subject" }`. For a pin that declares a `linked` or `unscheduled` slot,
  `runPackages` refuses the question with its existing "question has no supported captured
  evidence recipe" error.
- **One package per subject item.** `runPackages` packages every item of the pinned
  `subject.item_kind` in each subject revision whose recorded provenance matches the question's
  pinned expectation. Each package's `revision_id` is that revision's id. A subject that
  declares no links, or links that resolve to nothing, is packaged like any other. Nothing is
  excluded, so the build adds no exclusions. Each packaged subject's decision is `eligible`,
  naming its package's evidence set.
- **Package contents.** A package holds exactly one reference per subject slot, in pinned slot
  order (input slots, then output slots). Each is the same captured reference the existing builds
  give a subject slot: ref `<role>:<producer local id>`, kind from the field's declared
  classification, the item's selected value as content, and its `oakridge://revision/...` deep
  link. The evidence set is complete (`is_incomplete: false`, `incompleteness_reason: null`).
- **Unsupported provenance.** A revision whose provenance does not match the pin keeps the
  `inapplicable` decisions it gets today, and none of its items is packaged.

Existing builds, pins and questions must behave exactly as before. A question pinning
`linked_sources` over the same revisions still excludes an uncited subject.

The public checks are `bun test ./tests/visible` and
`tsc --noEmit -p tsconfig.json`. The evaluator also runs private feature and
regression checks. Keep the implementation within the existing source tree. You
may add tests of your own under `tests/agent/`; they are not graded.
