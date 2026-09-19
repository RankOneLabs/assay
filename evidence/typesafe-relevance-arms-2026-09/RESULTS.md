# Typesafe relevance — mirror-arm grid results

Run date: 2026-09-18. Design, inputs and caveats: `PLAN.md`.

n=79 frozen evaluations, 49 human-positive (62.0% base rate), 30 human-negative.
Three repeats per cell, majority decision. 948 cells dispatched, 0 failures.

## Headline table

| Arm | Correct | Accuracy | Precision | Recall | McNemar p vs production |
| --- | ---: | ---: | ---: | ---: | ---: |
| production (frozen) | 65/79 | 82.3% | 79.7% | 95.9% | — |
| `gemini:v2` | 55/79 | 69.6% | 87.9% | 59.2% | 0.1102 |
| `gemini:v1` | 52/79 | 65.8% | 89.3% | 51.0% | 0.0351 |
| `jev:v2` | 52/79 | 65.8% | 78.9% | 61.2% | 0.0294 |
| `jev:v1` | 49/79 | 62.0% | 74.4% | 59.2% | 0.0070 |
| `haiku:v2` | 46/79 | 58.2% | 83.3% | 40.8% | 0.0026 |

## Finding 1 — the model is not the binding constraint

The 2x2 decomposes additively, with no interaction:

| | v1 criteria | v2 criteria | wording effect |
| --- | ---: | ---: | ---: |
| **Typesafe jev** | 62.0% | 65.8% | +3.8pp |
| **Gemini 2.5 Flash** | 65.8% | 69.6% | +3.8pp |
| **model effect** | +3.8pp | +3.8pp | |

Each swap is worth exactly three cases. Neither is significant at n=79
(`jev:v1` vs `gemini:v1` p=1.0000; `jev:v2` vs `gemini:v2` p=0.5488;
`jev:v1` vs `jev:v2` p=0.5078; `gemini:v1` vs `gemini:v2` p=0.5488). The best arm
in the grid still sits 12.7pp below production.

Swapping in production's own model, on production's own population, against
production's own frozen decisions, moves the needle by three cases. **The primary
report's 20-point gap is not a Typesafe deficiency.** That hypothesis is the one
this run was built to falsify, and it failed to survive.

Haiku is the only arm separable from another arm: `gemini:v2` vs `haiku:v2`
p=0.0225. A weaker model does worse on the same questions, which is the sanity
check that the harness can detect a model effect when one exists.

## Finding 2 — better criteria help, consistently but slightly

v2 beats v1 by exactly +3.8pp on both models it was tested on. Directionally
consistent replication across two independent vendors is the strongest claim the
sample supports; neither individual comparison reaches significance.

The structural change is larger than the accuracy change. The `out_of_scope` band
was **dead** under v1 — zero argmax cases for Jev across all 79 — and comes alive
under v2 with 9, of which 8 land on human-negatives. `pointer` firing on negatives
halves, 14 → 7. Precision rises on both models (`jev` 74.4% → 78.9%). So the
diagnosed defects (a dead band level, an exclusion/pointer overlap) were real and
the wording fix addressed them; it simply is not where the 20 points live.

## Finding 3 — the labels and the rubric disagree, and that dominates everything

Every arm is far more conservative than the labels:

| arm | says yes | TP | FP | FN | TN | miss rate on + | false-fire on − |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| production | 59/79 (74.7%) | 47 | 12 | 2 | 18 | 4.1% | 40.0% |
| `jev:v1` | 39/79 (49.4%) | 29 | 10 | 20 | 20 | 40.8% | 33.3% |
| `jev:v2` | 38/79 (48.1%) | 30 | 8 | 19 | 22 | 38.8% | 26.7% |
| `gemini:v2` | 33/79 (41.8%) | 29 | 4 | 20 | 26 | 40.8% | 13.3% |
| `gemini:v1` | 28/79 (35.4%) | 25 | 3 | 24 | 27 | 49.0% | 10.0% |
| `haiku:v2` | 24/79 (30.4%) | 20 | 4 | 29 | 26 | 59.2% | 13.3% |

Production's advantage is almost entirely recall: it fires on 75% of the population
against a 62% base rate and misses only 2 of 49 positives. Every catalogue arm's
dominant error is the false negative, by a factor of two to seven.

Two numbers make this decisive:

- **15 of the 49 human positives are rejected by all five arms** — two vendors,
  three models, two catalogue versions, unanimous. Model error does not replicate
  like that, and neither does wording error.
- **A per-case oracle over all five arms caps at 78.5%** (62/79), still below
  production's 82.3%. No selection among these arms, however favourable, closes the
  gap.

The `agent-ops-relevance` rule is *deliberately narrower* than the "relevant in
general" rubric these 79 labels were assigned under: it is designed to reject
general agent-building content and bare pointers. It is doing exactly that, and
being scored wrong for it. For reference, a trivial always-yes classifier scores
62.0% on this label set — identical to `jev:v1`.

## Verdict

**On the question this run was built to answer:** the questions, not Typesafe. Two
independent models answering the same catalogue land in the same band as Jev, and
the model swap is worth three cases against a twenty-case gap. Nothing here
supports "Jev is weak"; `jev:v2` is statistically indistinguishable from
`gemini:v2`, which is production's own model.

**On adoption:** this run authorizes nothing, in either direction. The
arm-versus-production column is confounded by a rubric mismatch large enough to
account for the whole gap, so neither "Typesafe lost" nor "the catalogue lost" can
be read off it. The primary report's adoption conclusion — do not build the
Typesafe backend from it — stands unchanged, but its stated *reason* does not
survive this run.

**Blocking next step:** relabel the 79 cases under the `agent-ops-relevance/v1`
four-band rule. Until the labels and the decision rule ask the same question, no
number computed against these labels means what it appears to mean, and the ceiling
for every arm including production is unknown.

---

## Follow-up: the relabel ran, and it did not unblock the number

Added 2026-09-19, after
[`../typesafe-relevance-census-2026-09/RESULTS.md`](../typesafe-relevance-census-2026-09/RESULTS.md).

All 79 cases were relabelled blind under `agent-ops-relevance/v2`. The rubric
mismatch above is **confirmed** — on the 15 `crux` cases the reviewer sided with
the arms on 12, so the arms were applying the rule correctly and the stored labels
were answering a broader question.

The adoption number still does not follow. 30 of the 79 cases were re-presented
unmarked from the earlier packet, and the band question reproduces against itself
at only **19/30 = 63%**, with 6 of the 11 disagreements two rungs apart. `exclusion`
holds at 90% on the same cases, so this is specific to the band question rather than
general reviewer noise. The census PLAN.md declared before labelling that a low floor
invalidates the comparison rather than the labels, and it is a low floor: the gap
between the arms in the table above is smaller than the gap between one reviewer and
the same reviewer a day later.

Do not read an adoption verdict out of any band-mediated figure in this document.
The measured advantages of Jev that do **not** route through the band — latency and
the shape of its probability outputs — are unaffected.
