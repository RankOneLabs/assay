# Typesafe relevance — mirror-arm grid

Run date: 2026-09-18

Assay base commit: `cbc0b8e2086b220c3b2e84933066c16d15e50e33`

Scout population commit: `53cba8b8dd7eca1b426fa3cc4c55a0d654271f91`

## Why this run exists

The primary report established that Typesafe lost to production (62.0% vs 82.3%,
McNemar p=0.0070) and the fitted rerun established that no threshold recovers it.
Neither report can say **why**, because both had one candidate arm. "The Typesafe
service is weak" and "the question catalogue is weak" predict exactly the same
numbers when the catalogue is only ever answered by Typesafe.

This run adds the missing control. The same catalogue is rendered as an LLM system
prompt plus a strict JSON schema and answered by two other models, so a model swap
and a wording swap can each be measured while the other is held fixed.

## Design

A 2x2 over {answering model} x {criteria wording}, plus one extra model on v2.

| arm | model | catalogue | dispatched |
| --- | --- | --- | ---: |
| `jev:v1` | Typesafe `jev-latest` | v1 | reused from the primary report |
| `jev:v2` | Typesafe `jev-latest` | v2 | 237 |
| `gemini:v1` | `google/gemini-2.5-flash` | v1 | 237 |
| `gemini:v2` | `google/gemini-2.5-flash` | v2 | 237 |
| `haiku:v2` | `anthropic/claude-haiku-4.5` | v2 | 237 |

Gemini 2.5 Flash is production's own model, which makes `gemini:v1` the sharpest
available control: same model as the 82.3% reference, same questions as the 62.0%
candidate. Haiku is a second, unrelated vendor — a check that any model effect
replicates rather than being one model's quirk.

`jev:v1` never dispatched. Its 237 stored answers are reused verbatim from
`typesafe-relevance-primary-2026-09`, so that row is byte-identical to the
published primary result and the comparison is anchored to it.

## Frozen inputs

- Population: the same 79 distinct frozen evaluations as the primary report —
  agent-ops snapshot `cb09c4f0` (51) plus agent-evals snapshot `33bf631e`
  excluding the 45 `GAIA`-route rows (28).
- Population SHA-256: `6c3d18de02e35f33a432be9f9bda57d36d22478a69fad94c42d924d4ccc9782a`,
  verified equal to the value recorded in the primary report's `checksums.json`.
- Catalogue v1 version: `019c2b2ad3872710e0324d190a918bdfd5030612b013a8d6885186d261366e46`.
- Catalogue v2 version: `5c24fb98f3d9e1b426afe6701ad6eb903550c123a1958a1e7b3cf6cac10a48e7`.
- Decision mapping: `agent_ops_relevance/v1` (`decide_argmax`) for every arm,
  unchanged from the primary report. Majority over three repeats.
- Reference: the production score and decision frozen with each Scout evaluation.
- Three repeats per cell; Typesafe SDK retries disabled; LLM arms at temperature 0
  with `strict: true` structured output, `allow_fallbacks: false`,
  `data_collection: deny`, `require_parameters: true`.

948 cells dispatched against a hard budget of 1000. Zero failures. A short or
malformed reply is recorded as a failed cell, never as a silent negative.

## What v2 changes, and what it does not

v2 is a **wording-only** revision. It carries the same 17 question ids in the same
order, the same answer types, and the same answer domains as v1 — asserted by test,
not by inspection. Any v1/v2 difference is therefore attributable to criteria text
and to nothing else.

v1 was the schema spec's unfinalised first draft: 40 bare `what:` strings, zero
`examples`, zero `not_for`, against a spec that required both. v2 supplies 40
`examples` and 8 `not_for` blocks, replaces tautological false criteria with the
confusable near-miss, gives the Score levels prose rather than enum slugs, restores
a precedence warning v1 had dropped, and states explicitly that thin or off-topic
content is not an exclusion.

All examples are synthetic. None is drawn from the 79 scored cases, and none from
the September 11 held-out cohort, so no question is fitted to the test set.

## The mirror arm

`render.py` is a pure transform from the loaded catalogue document to (a) a system
prompt and (b) a strict JSON schema, plus a normalizer from the LLM's JSON reply
back into Jev's answer shapes. Both backends therefore derive from the one loaded
document; there is no hand-maintained second copy of the questions to drift.

Because the LLM arms are normalized into Jev's shapes, every downstream decision
mapping is backend-agnostic and the same `decide_argmax` scores all five arms.

`confidence` for the LLM arms is defined as the top probability. No decision
mapping in this run reads `confidence`, so that definition affects nothing scored
here.

## Protocol notes

1. As in the primary report, the production arm is the frozen recorded decision,
   not a rerun. This report must not be represented as evidence about production
   repeat variance.
2. At temperature 0 with structured output, both LLM arms return hard 0.0/1.0 on
   most questions despite being asked for spread probability. The LLM arms are
   therefore comparable at argmax but do not yield usable calibration curves. No
   claim in `RESULTS.md` depends on LLM probability mass.
3. **The 79 human labels were assigned under the earlier "relevant in general"
   rubric, not the `agent-ops-relevance` four-band rule the catalogue encodes.**
   Every arm is scored against the same labels, so within-run contrasts are valid.
   Arm-versus-production contrasts are not clean, and cannot produce an adoption
   number. See `RESULTS.md`.

Raw post text stayed in the private run-receipts export and is not committed here.
`exported-answers.json` carries evaluation identifiers, labels, production outputs,
per-arm answer vectors, deterministic decisions, model names, usage, latency and
request identifiers; it contains no post state or text.
