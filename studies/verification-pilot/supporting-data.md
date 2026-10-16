# Supporting data: verification after a contributor handoff

This document supports the [live study page](README.md). **Results are in
progress.** The committed fixture and evaluator code establish the design;
no live route count is inferred from scripted smoke runs.

## Method and analysis

The source is the pinned 62-file Oakridge workflow slice described in
[`DECISIONS.md`](../../experiments/verification_pilot/DECISIONS.md). Four
migrations each supply four remnant locations, one per ownership group. Three
rotations change the position of the contributor accounts. Rotation is a
subject attribute, giving 48 distinct subject digests and 48 potential
native/quoted pairs per route. The evaluator id carries turn and ownership
group; the report derives each remnant's block position from that declared
rotation and group.

The report reads terminal evaluation verdicts only after `verify_manifest`
succeeds. It emits counts by model, arm, turn, remnant location, block position,
evaluator, and verdict; an escalation chart for T1–T3; the first-wide-search
ceiling fraction per arm and route; and per-model operating cost. Cross-model
tables are assembled from separate route reports. Both the Assay engine report
and each source manifest have exact-closure export bundles. Run
`assay verify <bundle-directory> <root-ref>` offline to check an exported root.
The static HTML review export uses Assay's existing review path where its
64 MiB budget allows it. This pilot's snapshot closure exceeds that budget;
the exporter writes a notice to use the local Assay review server with the
offline-verifiable bundle.

| Hypothesis | Comparison | Analysis and realized design n |
| --- | --- | --- |
| H1 | T1 ownership gap against zero, separately per arm and model | Pilot module calls `report_engine.exact_sign_test` on positive and negative gaps, excluding zero ties; 48 rotated observations per arm at full Tier 1 size. |
| H2 | Native versus quoted T1 ownership gap, same subject | `build_report` with `paired-v2`, alpha 0.05, engine 0.1.0; 48 subject pairs per model. |
| H3 | Tier 2 native versus quoted, same subject | `build_report` if Tier 2 qualifies; 12 of 16 base subjects valid in both arms. Tier 2 is currently deferred. |
| H4 | Own versus teammate remnant, within one arm | Pilot module groups different subjects by migration, averaging rotations within each group; 4 migration-matched pairs. Descriptive only, with no engine p-value. |

**Acceptance criterion for inference:** two of the four preregistered numbers,
H1 and H4, come from pilot code rather than the shared report engine. They
therefore have their own tests, including a hand-computed H1 p-value and an H4
between-subject case. H2 and eligible H3 use the engine's paired comparison.
The shared `ReportConfig`, `StatisticalProfile`, and engine are unchanged.

## Gates and limits

The [smoke rule](../../experiments/verification_pilot/SMOKE.md) requires manual
review of both route smokes and records each arm's first-wide-search share.
If that share exceeds 50% in either arm of a route, E1 escalation order, E2
untouched remnants, and E4 test masking lead that route's results; H1–H3 become
secondary. A repository-wide first search can inspect every ownership group
at once, compressing ownership gap independently of the handoff presentation.

The full 288-cell ceiling is a capacity bound across declared tiers. Tier 2
stays excluded after the local on-policy generation probe discarded 4 of 4
attempts, and the paid route needs its own measured supply and budget gate.
H4's four matched pairs cannot support the engine's inference floor of ten;
the published H4 result carries its n and effect estimate without a p-value.
The current subject payload identifies four contributor ownership groups but
does not designate one as the verifier's own group. The H4 report therefore
requires an explicit `own_group` input and is descriptive until that assignment
is fixed by the study operator; a supplied group must not be inferred from the
observed verdicts.
