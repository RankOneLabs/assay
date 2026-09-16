# Fixed legacy 0.1.0 report bundle fixture

`bundle/` is a checked-in, content-addressed object store: a persisted
`assay-report/0.1.0` report over a two-subject `assay-execution-plan/0.1.0` run, and its
complete reference closure (manifest, plan, snapshot, evaluation/operating records,
schemas), produced by `execute_plan` + `persist_report` + `export_bundle` against a
`test_execution.execution_fixture(store, subject_ids=("alpha", "beta"), worker_repeats=1,
evaluator_repeats=1)` snapshot.

It exists to give `tests/test_legacy_report_bundle.py` a byte-for-byte fixed compatibility
baseline rooted at a *report*, not just a manifest: `build_report` recomputation over
this fixture's pinned config must reproduce the exact same report document and digest,
entirely offline, in a process that never imports Jig. This complements
`tests/fixtures/legacy-0.1.0-bundle` (manifest-rooted) by pinning the report engine's
output too.

Root: `sha256:c89c984a842bd43d60f6b504b1465e76fda06554981f7fe20e97e9a1b329b91c` (the
persisted report). 55 objects, ~252 KiB total.

**Do not regenerate this fixture.** It is a fixed point, not a snapshot of "whatever the
current code produces" -- regenerating it would defeat its purpose of catching an
unintended behavior change in report recomputation. If the legacy 0.1.0 report contract
ever needs to change on purpose, that is a decision to make explicitly, not a side effect
of updating a fixture.
