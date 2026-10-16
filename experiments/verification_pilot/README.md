# Verification pilot Tier 1 fixture

The pilot pins the wf-13 oakridge-dbos slice and declares four symbol
migrations over it. `fixture.load_fixture()` validates file and byte limits,
recomputes the tree digest, and checks every declared use site. The rename
generator produces a complete renamed tree; `ground_truth.py` then injects
three deliberate remnants and three decoys for verification experiments.

The Part 2 path-overlap test is deferred pending the frozen 2b anchor list.

`verification_pilot.bridge.create_pilot_agent()` passes the frozen settings
into the repository agent, including writable prefixes and both tool-call
limits. The committed `PILOT_TOOLS_SHA256` note is checked against the pilot
tool schemas by the settings test.

The pilot bridge records each turn's workspace diff against cell start when
that turn submits. If a tool-call cap or another stop cause ends a turn before
submission, its `workspace_diff` is null. Phase-2 reporting should therefore
count available diffs rather than assume three diffs for every cell.

The full experiments suite needs Node tooling, including `jscpd`, Bun for the
masking test, and a passwordless mount for its mount-dependent tests. Without
those prerequisites, full-suite failures or hangs outside this pilot should not
be read as pilot regressions. The focused pilot tests can be run with
`pytest experiments/verification_pilot/tests`.
