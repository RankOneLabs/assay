# Verification pilot smoke and decision gate

This rule is fixed before any live Tier 1 cell. The scripted grid is run with
`uv run --project experiments python -m verification_pilot.run scripted --store /tmp/vp-scripted`.
It must produce 96 successful cells and one value for each of the 57 declared
evaluators on each cell. It uses no model route. The exact 0.3.0 plan, snapshot,
runtime configuration, and final ceiling are retained in the object store.

The live smoke takes two migrations (`json_value`, `stage_instance_id`), four
locations each, one rotation (r0), and both Tier 1 arms: 16 cells **per route**.
Run the local shard with `uv run --project experiments python -m
verification_pilot.run live-smoke --store /tmp/vp-live-smoke --image <pinned-image>
--routing-config <routing-file>`. The snapshot retains all 48 subjects and
all tier arms while the plan excludes cells outside the 16-cell smoke shard.
With an operator-provided `OPENROUTER_API_KEY`, run the paid shard using the
same command and `--route openrouter --store /tmp/vp-paid-live-smoke`. The
route identity is pinned by `assay_pier_bridge.protocol.ModelRoute`; record
the exact model and provider supplied by `vp-frontier-route` before dispatch.
Read every trajectory, tool result, submission, and workspace diff by hand.
Record, per route and arm, counts and denominators for `conversation_limit`,
`no_tool_call`, refusals, tool errors, and explicit misattribution of the quoted
“You” block. The route passes only if all five counts are zero in the 16-cell
smoke. If the local route fails this gate, report Tier 1 on the passing model
alone and state the excluded route; do not treat its null ownership gap as a
behavioral null. H1 is always reported separately per model.

For each route and arm, report the fraction of T1 cells whose first inspection
is a repository-wide search for the old symbol. **If that fraction exceeds
50% in either arm on a route, lead with E1 (order), E2 (untouched remnants),
and E4 (test masking) for that route.** H1, H2, and H3 become secondary
because a flat search can mark every ownership group inspected at once. Keep
the precommitted order even if the resulting null is attractive. Record the
cross-directory ownership stratum separately.

The final plan ceiling is 288 cells, 345,600 wall seconds, and one active
worker. Tier 1 uses 96 cells; Tier 2 and Tier 3 arms are declared and excluded
from this shard. A later shard may change exclusions and population while
keeping this ceiling, runtime configuration, worker repeats, and all other
report compatibility fields fixed. The 288-cell ceiling is a capacity bound,
not a commitment to execute deferred cells. Before Tier 2, measure the
on-policy block discard rate on one migration on each route: count a generated
block as discarded if tests fail, the old symbol remains in its assigned share,
or it edits outside that share. Record numerator, denominator, route, model,
and trace refs. Do not execute Tier 2 cells during this qualification.
Run local generation with `uv run --project experiments python -m
verification_pilot.run on-policy-local --store /tmp/vp-on-policy --image
<pinned-image> --routing-config <routing-file>`; it is outside the cell runtime.
Use `on-policy-paid --store /tmp/vp-paid-on-policy --image <pinned-image>`
with the operator-provided `OPENROUTER_API_KEY` for the same four locations on
the paid route. The current local probe discarded 4/4 attempts and accepted
zero; Tier 2 remains excluded. The 288-cell ceiling is the full-grid bound,
not an empirical supply estimate.

The paid route's dollar cap is an operator gate carried in the runtime
configuration and checked against `report_engine.summarize_operating` before
dispatch; the `ExecutionCeiling` wire type has no dollar field. The frontier
route cohort must supply the model identity and budget before a paid smoke.
