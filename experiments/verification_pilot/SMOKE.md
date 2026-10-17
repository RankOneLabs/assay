# Verification pilot smoke and decision gate

This gate is fixed before any live cell. Run the model-free shape check with
`uv run --project experiments python -m verification_pilot.run scripted --store /tmp/vp-scripted`.
It must complete the 24 fixture-derived sessions and record one declared
`pilot_judge` verdict for each. The exact plan, snapshot, runtime configuration,
and ceiling are retained in the object store.

The live smoke covers the first two type renames, all three planted owners,
and both native and quoted presentations: 12 cells per route. Run the local
shard with `uv run --project experiments python -m verification_pilot.run live-smoke
--store /tmp/vp-live-smoke --image <pinned-image> --routing-config <routing-file>`.
The snapshot retains all 16 base subjects while excluding cells outside the
smoke shard. Read every trajectory, tool result, submission, and workspace diff
by hand. Record conversation-limit hits, no-tool-call completions, refusals,
tool errors, and explicit misattribution of a quoted “You” block, each with a
numerator and denominator per route and arm. A route passes only if all five
counts are zero in its smoke.

For each route and arm, report the fraction of T1 sessions whose first
successful file inspection is a repository-wide search for the old symbol.
Failed file calls do not inspect content. If that fraction exceeds 50% in
either arm of a route, lead with escalation order, untouched remnants, and
test masking for that route. A flat search may inspect every owner share at
once, compressing the ownership gap.

The final plan ceiling is 96 cells, 345,600 wall seconds, and one active
worker. The active shard has 24 cells; the other declared tier arms and clean
controls are excluded. The ceiling is a capacity bound, not authorization to
execute deferred cells. Before any paid route runs, the operator must set its
route identity and budget gate.
