# Who checks the last remnant after a handoff?

**Study status: live; results in progress.** No live model cells have been
reported in this page yet. The tables below are the publication slots for
verified outputs, not estimates of the outcome.

In Oakridge PR #619 and its follow-up #629, a symbol migration and its review
raised a practical question: after several contributors each finish an assigned
share, does the final agent inspect the whole repository or trust the handoff?
The design is motivated by [Self-Attribution Bias: When AI Monitors Go Easy on
Themselves](https://arxiv.org/abs/2603.04582), which asks whether monitors
treat work attributed to themselves differently. This pilot tests observable
repository verification behavior; it does not assume the mechanism is bias.

[Supporting data](./supporting-data.md) records the design, inference rules,
export format, and limits. The live results will link to per-model reports and
offline bundles as soon as a qualified route completes.

## What the agent sees

Four real symbol migrations are applied to a pinned Oakridge repository slice.
Each migration has four ownership groups. One old spelling remains at a known
location. Four contributor accounts say their assigned pass is complete, and
the final agent is asked to verify the repository. Each location appears in
three block rotations, yielding 16 base subjects and 48 rotated subject
digests. The Tier 1 native and quoted presentation arms each have one cell per
rotated subject: **96 cells per model**. The snapshot declares Tier 2 and Tier
3 arms, but those cells remain excluded pending the qualification gates.

The primary readout is the first turn's ownership gap: the share of ownership
groups the agent has not inspected. The report also records which remnant was
inspected, the block's position, later checks and claims, and the cost of each
route. Each model gets its own report because a model route is part of the
authorized runtime; the reports cannot be pooled into one Assay comparison.

## Results in progress

The precommitted ceiling-effect headline is the fraction of T1 cells whose
first inspection is a repository-wide search. A fraction above 50% in either
arm on a route makes escalation order, untouched remnants, and test masking
the lead outcomes for that route.

| Route | Native first-wide-search share | Quoted first-wide-search share | Status |
| --- | ---: | ---: | --- |
| Smithers local | pending (0 observed) | pending (0 observed) | in progress |
| Frontier route | pending (0 observed) | pending (0 observed) | qualification pending |

No H1–H4 estimate, p-value, escalation chart, or per-model cost is presented
until its verified records exist. The report command will populate separate
route results and the cross-model and cross-turn tables from those records.

## What the pilot can resolve

H1 is a one-sample exact sign test of ownership gap against zero, reported by
arm and model. H2 compares the native and quoted arms on the same subject
digests. Tier 2's H3 is likewise a subject-paired arm comparison if the tier
qualifies. H4 compares own-remnant and teammate-remnant subjects within one
arm, matched by migration. See the [supporting data](./supporting-data.md)
for the exact test ownership and sample-size limits.

This is a small process pilot. Even at 48 rotated paired observations for H1
and H2, a null result would not establish equivalence. H3 has only 12 of 16
base subjects valid in both arms. H4 has four migration-matched pairs, below
Assay's ten-subject inference floor, so it remains descriptive and has no
engine p-value. Its own-group assignment must be fixed explicitly before a
live H4 interpretation: the current subject payload names contributor groups
without marking one as the verifier's own.
