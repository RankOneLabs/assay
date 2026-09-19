# relevance-census-2026-09 — results

Blind relabel of all 79 frozen evaluations under `agent-ops-relevance/v2`.
Labelled 2026-09-19 by a single reviewer, 79/79 complete.

Packet digest: `11b4c1e11fdbb3b7859fa91767294e92e2791a2528e49e5b2c44c37647f0f97a`

Reading digest: `0354f67a39e24e2120e005ab2e14e461c57483af82bab52ebd5a7da0e5394e81`

This run answers the blocking next step left open by
[`../typesafe-relevance-arms-2026-09/RESULTS.md`](../typesafe-relevance-arms-2026-09/RESULTS.md):
relabel the 79 cases under the four-band rule so the labels and the decision rule
ask the same question.

## Headline

**The relabel is done and it does not produce an adoption number.** The band
question retests at 63% against itself across two sittings by the same reviewer.
Every arm-versus-arm accuracy figure computed through the band is capped by that
floor, and the gap between the arms in the earlier run is smaller than the gap
between one reviewer and the same reviewer a day later.

PLAN.md declared this test before any label existed and declared what a bad result
means: *"A low floor invalidates the comparison rather than the labels."* It is a
low result. The labels stand as the label of record; the comparison they were
collected to enable does not.

## What was labelled

| band | n | | disposition | n |
| --- | ---: | --- | --- | ---: |
| `out_of_scope` | 12 | | `respond` | 22 |
| `building` | 16 | | `review` | 22 |
| `pointer` | 19 | | `drop` | 35 |
| `substantive` | 32 | | | |

`disposition` was asked directly rather than derived from the band, because the
band rule cannot be measured against a target computed from itself.

On the `crux` stratum — the 15 cases where all five arms rejected a case the
stored label called positive — the reviewer sided with the arms on 12. The rubric
mismatch that voided the arms run is confirmed: the arms were applying the rule
correctly and the stored labels were answering a different question.

## The noise floor

30 of these 79 cases were labelled in the earlier `relevance-rubric-2026-09`
packet. They were re-presented unmarked and in a different display order, with no
indication that they had been seen before.

| question | agreement across sittings |
| --- | --- |
| `exclusion` | 27/30 = **90%** |
| gate decision | 23/30 = **77%** |
| `band` | 19/30 = **63%** |

The band disagreements are not near-misses. Of the 11, **6 are two rungs apart** —
the same post read as `building` once and `substantive` the other time, or
`out_of_scope` once and `pointer` the other.

`exclusion` at 90% shows this is not general reviewer noise. The exclusion question
asks whether one of seven named categories fits the post's subject, and it holds up.
The band question is the one that does not.

## The pre-registered link rule

PLAN.md declared `pointer` + the post text contains a link as an approximation of
`disposition == review`, to be reported as precision and recall. It was declared a
measurement, not a threshold to pass.

| rule | fires on | correct | precision | recall |
| --- | ---: | ---: | ---: | ---: |
| `pointer` → review | 19 | 8 | 42% | 8/22 = 36% |
| `pointer` + link, URL required | 8 | 4 | 50% | 4/22 = 18% |
| `pointer` + link, URL or bare domain | 13 | 5 | 38% | 5/22 = 23% |

"Contains a link" is ambiguous between a literal URL and a mentioned domain, so both
readings are reported. The link test roughly halves recall under either, and moves
precision by less than the spread between the two definitions. It does not earn its
place.

The decisive number is definition-independent: **14 of the 22 `review` cases are not
in the `pointer` band at all** — 10 of them are `substantive`. Wanting a human to
glance at something is not the same judgment as noticing its substance sits behind a
link, and no pointer-based rule can reach most of it.

## What the band can predict

Mapping each band to its most common disposition — the best possible band-mediated
predictor, fitted in-sample with no holdout — gives **57/79 = 72%**, against a
majority-class baseline of 44%.

| band | respond | review | drop |
| --- | ---: | ---: | ---: |
| `out_of_scope` | 0 | 0 | 12 |
| `building` | 0 | 4 | 12 |
| `pointer` | 0 | 8 | 11 |
| `substantive` | 22 | 10 | 0 |

72% is the ceiling given a *perfect* band label. Since the band label itself only
reproduces at 63%, the achievable figure is well below it. The two ends behave:
`out_of_scope` is always drop, `substantive` is never drop. The middle does not —
`pointer` splits 8/11 between review and drop, which is close to a coin flip.

## Why the band is unstable

Two structural properties of the ladder, both readable off the catalogue text.

**The rungs measure two different things.** Levels 0 and 1 ask about *subject* —
is this about operating agents, or about building them. Levels 2 and 3 ask about
*substance* — does the post's own text make a point. A post can be about building
agents and make a specific operational point; it has a defined answer under the
ordering rule, but the reviewer has to hold two independent judgments on one column
and pick a single rung.

**The criteria summaries overlap where the ordering rule silently resolves them.**
The `pointer` summary lists *announces* among its signals. The `substantive` summary
requires "a specific claim, number, cause or practice in the post's own words." A
release announcement carrying a concrete claim satisfies both. `apply_in_order` does
resolve this — it tests substantive before pointer, so substantive wins — so the
outcome is defined. But a reviewer reading the criteria summaries, which is how the
question presents itself, sees two descriptions that both fit and no cue that the
order decides it.

Both are mechanisms consistent with a 63% floor. Neither is proven to cause it by
this run; separating them needs a sitting that asks the two axes as two questions.

## Prior exposure is not a confound

The 30 repeated cases had been seen before in a context where model grades were
visible, raising the question of whether the second sitting drifted toward the
machine. Measured against production's decision on the same cases:

- 16 cases where the first sitting disagreed with production: **3** flipped toward
  production, **13** held.
- 14 cases where the first sitting agreed with production: **4** flipped away.

Net drift toward the machine: **−1 case**. The instability is real but it is not
anchoring — the disagreements are stable, they just land on different rungs.

## Limits

- **One reviewer.** This measures self-consistency, not inter-rater agreement. A
  second reviewer would likely score lower, so 63% is an optimistic floor.
- **n=30 for the retest.** The 63% carries roughly ±9pp of sampling error; the
  qualitative finding that band is far less stable than exclusion survives that,
  the exact figure does not.
- **The band-to-disposition mapping is in-sample.** 72% is a ceiling, not an
  estimate of held-out performance.
- **The link-rule definitions were settled after seeing the data**, because PLAN.md
  did not pin one. Both are reported for that reason.
- **Post text, authors, URLs and the reviewer's free-text notes are not published
  here.** They stay in the private run receipt.

## Provenance

- `census-labels.json` — per-case labels keyed by `evaluation_id`, with the earlier
  sitting's labels attached to the 30 repeated cases. No post text.
- `PLAN.md` — the pre-registration, written before any label existed.
- Private run receipt: `run-receipts/typesafe-relevance-2026-09/label-census/`.
