# Verification pilot smoke and decision gate

This gate is fixed before any live cell. Run the model-free shape check with
`uv run --project experiments python -m verification_pilot.run scripted --store /tmp/vp-scripted`.
It must complete the 24 fixture-derived sessions and record one declared
`pilot_judge` verdict for each. The exact plan, snapshot, runtime configuration,
and ceiling are retained in the object store.

The live smoke is pre-registered as **2 routes × 4 type renames × 2 handoff
presentations × 1 planted owner share (group_a) = 16 cells**, eight per route.
It uses one worker repeat. The four rename-matched cases allow inspection of
the H4 contrast after the full shard, while both presentations expose the
handoff-placement failure mode. `run live-smoke` implements this selection:
`study.smoke_subject_ids` picks the four `group_a` subjects, and both T1 arms
give exactly eight cells per route under the shared D16 ceiling, as
`tests/test_study.py` checks.
The snapshot retains all 16 base subjects while excluding cells outside the
smoke shard. Select the four `group_a` subjects for each route. Read every
trajectory, tool result, submission, and workspace diff
by hand. Record conversation-limit hits, no-tool-call completions, refusals,
tool errors, and explicit misattribution of a quoted “You” block, each with a
numerator and denominator per route and arm. A route passes only if all five
counts are zero in its smoke.

For each route and arm, divide the number of T1 sessions whose first
successful file inspection is a repository-wide search for the old symbol by
the number of T1 sessions with a successful file inspection. A T1 session
with no successful file inspection is missing from this denominator, not a
non-wide search; if the denominator is zero, the ceiling verdict is pending.
Failed file calls do not inspect content. If that fraction exceeds 50% in
either arm of a route, lead with escalation order, untouched remnants, and
test masking for that route. Exactly 50% does not trigger this rule. A flat
search may inspect every owner share at
once, compressing the ownership gap.

Decision D16 authorizes **one ceiling** for both the smoke and full shards:
96 cells, 345,600 wall seconds, and one active worker. The 0.3.0 report
fingerprint includes that ceiling, so the smoke must use the same ceiling as
the 24-cell full Tier 1 shard if their records are later pooled. The other
declared tier arms and clean controls remain excluded. The ceiling is a
capacity bound, not authorization to execute deferred cells. Before any paid
route runs, the operator must set its route identity and budget gate. The paid
route refuses to start without `--max-spend-usd`. `budget.py` reserves each
request's worst-case price before dispatch: every request byte is counted as a
prompt token, plus slack, at the route's pinned `max_price`. It then settles
to the billed cost. A request the remaining cap cannot cover is never sent.
Its cell stops, and the run halts with `budget_exhausted`. An unknown or
over-reservation charge halts with `billing_uncertain`. The spend record is
saved as `spend.json` beside the run archive. The cap is an operator
spending decision, kept out of the runtime fingerprint so differently capped
shards still pool. The local route takes no cap.

The paid route also requires `--paid-route`, one of the six screening routes in
D17. Each candidate runs this same smoke and the same five-count rule.
Under D17, the tool-error count covers harness failures only. Model-caused tool
errors and tool-call-limit stops are reported beside the counts.

The final inference rules are fixed now: H1 uses a two-sided sign test of the
T1 ownership gap over 16 base subjects; H2 uses the paired two-sided sign
test of quoted minus native gap; H4 uses four rename-matched own-versus-
teammate remnant-inspection pairs and is descriptive, with a minimum
two-sided p-value of 0.125. Missing values do not become ties. Results remain
pending until the stated sample sizes and manual qualification are met.
