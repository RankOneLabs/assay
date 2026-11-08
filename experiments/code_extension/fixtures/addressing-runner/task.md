# Add an addressing code runner for analysis findings

Add a code-graded question, "Is this analysis finding addressed by at least one proposed spec
update?", with a new `addressing` runner. It works like `assessment.coverage`: the producer
packages a small link view into each finding's evidence, and the runner decodes that view and
answers from it.

## The question

Add it to the Oakridge catalogue. `PILOT_QUESTION_IDS` lists `analysis.finding_addressing`,
and `oakridgeQuestions(expectations)` returns it under that id, with the expectation passed
for that id. Its definition:

| Field | Value |
| --- | --- |
| `question_id` | `analysis.finding_addressing` |
| `question_version` | `v1` |
| `target_item_kinds` | `["finding"]` |
| `response_kind` | `boolean` |
| `allowed_values` | `null` |
| `missing_evidence_policy` | `fail` |
| `requires_repository_snapshot` | `false` |

The question text and the semantics and caveat strings are yours to write. Its `input_recipe`
is exactly this slot recipe. It adds a new evidence role, `proposed_spec_update`.

```json
{ "recipe_version": "v1",
  "build": { "kind": "assessment_window" },
  "subject": { "artifact_kind": "analysis", "item_kind": "finding" },
  "input": [{ "role": "analysis_finding", "source": { "from": "subject" }, "min_count": 1, "max_count": 1 }],
  "output": [{ "role": "proposed_spec_update",
    "source": { "from": "linked", "link_type": "addresses", "direction": "in",
      "artifact_kind": "analysis", "item_kind": "proposed_spec_update" },
    "min_count": 0, "max_count": 100 }] }
```

A proposed spec update names the findings it addresses in `finding_ids`. Capture already
records each one as an `addresses` link from the `proposed_spec_update` item to the
`analysis`/`finding` item with scope `analysis/finding`.

## The package and its link view

`runPackages` must package each analysis finding for this question. A finding is packaged even
when no update addresses it, and its decision is `eligible`. Each package's references are,
in order:

1. The link view: `{ ref: "addressing_links:<subject occurrence id>", kind: "internal",
   content: <view>, digest: <canonicalDigest(view)> }`. It has no deep link, because no
   captured source holds it.
2. The finding's own captured reference, `analysis_finding:<finding id>`.
3. One captured reference per update that addresses the finding,
   `proposed_spec_update:<item path>`, in captured order.

The view is exactly:

```json
{ "analysis_finding": { "item_kind": "finding", "item_scope": "<finding item_scope>",
    "producer_local_id": "<finding id>" },
  "proposed_spec_updates": [
    { "item_kind": "proposed_spec_update",
      "links": [{ "type": "...", "target_artifact_kind": "...", "target_item_kind": "...",
        "target_scope": "... or null", "target_local_id": "..." }] }] }
```

`proposed_spec_updates` lists the updates that address this finding, the same items as
reference 3, in the same order. Each update's `links` copies all of that update's captured
links, with exactly those five fields. An update that addresses two findings appears, with
both links, in both findings' views. A finding no update addresses has an empty list.

The coverage question's link view (`coverage_links:...`) and its bytes must not change.
Evidence-set digests are computed over it.

## The runner

Register `addressing` in the runner registry as a `code` runner with `network: false`, whose
factory returns a code runner. Given a grading context, it:

- returns an error result, not an answer, unless the question has `response_kind: "boolean"`
  and pins a slot recipe with an `assessment_window` build;
- decodes the view from the `content` of the evidence's first reference, and returns an error
  result when that content is not an addressing view of the shape above (a coverage view, for
  example);
- answers `{ state: "answered", kind: "boolean", value }`, where `value` is true exactly when
  at least one listed update has a link with `type: "addresses"`, `target_artifact_kind:
  "analysis"`, `target_item_kind: "finding"`, a `target_scope` equal to the finding's
  `item_scope`, and a `target_local_id` equal to the finding's `producer_local_id`. A link of
  any other type, or to another scope, finding, item kind or artifact kind, does not count.

Existing questions, packages, runners and the coverage view must behave exactly as before.

The public checks are `bun test ./tests/visible` and
`tsc --noEmit -p tsconfig.json`. The evaluator also runs private feature and
regression checks. Keep the implementation within the existing source tree. You
may add tests of your own under `tests/agent/`; they are not graded.
