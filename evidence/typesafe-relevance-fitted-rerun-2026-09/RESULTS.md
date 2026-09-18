# Typesafe relevance fitted rerun results

The PR #40-style fitted mapping improved the untuned Typesafe result, but it still
did not beat Scout and is not eligible for adoption.

| Mapping | Accuracy | Precision | Recall |
|---|---:|---:|---:|
| Scout frozen production | 65/79 (82.3%) | 47/59 (79.7%) | 47/49 (95.9%) |
| Typesafe primary argmax | 49/79 (62.0%) | 29/39 (74.4%) | 29/49 (59.2%) |
| Typesafe fitted, out of fold | 54/79 (68.4%) | 40/56 (71.4%) | 40/49 (81.6%) |

Relative to the fitted Typesafe decisions, Scout alone was correct on 15 cases and
the fitted mapping alone was correct on 4. The exact McNemar p-value is
`0.0192108154296875`.

The fit recovered 11 false negatives compared with the untuned argmax mapping, but
introduced 6 additional false positives. It therefore improved accuracy by 6.3
percentage points and recall by 22.4 points while reducing precision by 3.0 points.
It remained 13.9 accuracy points and 8.2 precision points below Scout.

Verdict: **Typesafe did not win this exploratory fitted replay.** These out-of-fold
results are diagnostic only. The catalogue and mapping were not confirmed on a
fresh held-out cohort, so this report cannot authorize production adoption or the
hosted backend.
