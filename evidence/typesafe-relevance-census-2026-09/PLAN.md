# relevance-census-2026-09 — blind relabel census

Written 2026-09-19T01:08:55+00:00, before any label exists.

Packet digest: `11b4c1e11fdbb3b7859fa91767294e92e2791a2528e49e5b2c44c37647f0f97a`

Reading digest: `0354f67a39e24e2120e005ab2e14e461c57483af82bab52ebd5a7da0e5394e81`

Seed: `assay-relevance-census-2026-09/v1`

## Purpose

Produce an adoption-grade label set for all 79 frozen evaluations under the agent-ops four-band rule, plus the three-way disposition the decision mapping now has to produce. These labels replace the stored ones, which answer the older and broader 'relevant in general' question.

## Instrument

Every one of the 79 frozen evaluations, in seeded display order.
Blind: post text and parent text only — no author, no URL, no stored label, no
production decision, no arm decision, and no indication that a case was seen in
an earlier packet.

Three questions per case. `exclusion` and `band` are the catalogue's own gating
questions in its own unedited words. `disposition` is new and is the ground truth
for the three-way outcome: **respond**, **review**, **drop**. It is asked directly
rather than derived from the band, because whether a post earns a human's glance
is a judgment about value, not about where its substance sits — and because the
band rule cannot be measured against a target derived from itself.

## Population shape

Strata are how the five arms behaved, carried for reporting only. They are not
shown to the reviewer and do not affect selection: this is a census, not a sample.

| stratum | cases |
| --- | ---: |
| `crux` | 15 |
| `mirror` | 2 |
| `split_negative` | 10 |
| `split_positive` | 16 |
| `unanimous_no_negative` | 18 |
| `unanimous_yes_positive` | 18 |

## Declared before labelling

- **deterministic link rule** — `pointer` + the post text contains a link approximates `disposition == review`. Reported as precision and recall against the reviewer's disposition. This is a measurement, not a threshold to pass.
- **logistic fit** — 19 features over 79 rows is 4.2 rows per feature, so any fitted weight set is reported out-of-fold and is diagnostic only. No adoption claim may rest on an in-sample fit.
- **test-retest** — 30 of these cases were labelled in `relevance-rubric-2026-09`. Their band agreement across the two sittings is the label noise floor and is reported before any model comparison. A low floor invalidates the comparison rather than the labels.

## What these labels replace

The stored `human_label` on each evaluation answers "relevant in general" and is
retained for comparison only. After this census, `disposition` is the label of
record for the agent-ops project, and any figure scored against the stored labels
must say so explicitly.
