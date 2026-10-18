# Supporting data: verification after a contributor handoff

This document supports the [live study page](README.md). Results are in progress. The fixed design is in [DECISIONS.md](../../experiments/verification_pilot/DECISIONS.md); the model-free scripted run supplies no live observation.

## Method

The pinned 62-file Oakridge slice supplies four type renames with 20, 18, 10, and 8 whole-word use-site files. Each has three owner shares and a clean control. Historical decoys are planted only in generated workspaces. Native and quoted presentation of the 12 remnant cases yields 24 active sessions per route.

## Inference table

H1 is a two-sided sign test of T1 ownership gap over 16 base subjects. H2 is a paired two-sided sign test of quoted minus native gap. H4 uses group_a as the verifier-owned group, validated against subject payloads, and compares its remnant inspection with teammates within each of four renames; its smallest attainable two-sided p-value is 0.125 and it remains descriptive. Ties are excluded from sign-test denominators. The active Tier 1 shard has 12 planted subjects per arm; H1 stays pending until all 16 base subjects, including clean controls, have observations.

| Route | H1 observed | H1 p | H2 pairs | H2 p | H4 pairs | H4 p |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| smithers-local | 0/16 | pending | 0 | pending | 0/4 | pending |
| openrouter | 0/16 | pending | 0 | pending | 0/4 | pending |

## Wide-search ceiling

The denominator is T1 sessions with a successful file inspection in that arm. Sessions without one are missing and excluded; an arm with zero observed first inspections stays pending. Failed file calls do not count as inspections.

| Route | Native first-wide-search share | Quoted first-wide-search share | >50% ceiling | Status |
| --- | ---: | ---: | --- | --- |
| smithers-local | pending (0 observed) | pending (0 observed) | pending | qualification pending |
| openrouter | pending (0 observed) | pending (0 observed) | pending | qualification pending |

## Qualification and reporting

The [smoke rule](../../experiments/verification_pilot/SMOKE.md) requires manual review before results are interpreted. A first-wide-search share strictly above 50% changes the route's headline. The single authorized 96-cell ceiling applies to smoke and full shards. Route reports remain separate because route identity is part of the runtime fingerprint.
