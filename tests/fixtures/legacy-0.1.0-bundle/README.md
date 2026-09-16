# Fixed legacy 0.1.0 bundle fixture

`bundle/` is a checked-in, content-addressed object store: an exported
`assay-run-manifest/0.1.0` run and its complete reference closure, produced by
`execute_plan` against a two-subject, one-repeat, one-evaluator-repeat
snapshot (see `test_execution.execution_fixture`) and then `export_bundle`.

It exists to give `tests/test_legacy_bundle.py` a byte-for-byte fixed
compatibility baseline: a bundle that predates (and is untouched by) the
0.2.0 plan work in this change, verified/exported/indexed/rendered/recomputed
entirely offline, in a process that never imports Jig. The 0.1.0 wire shapes,
report engine and review stack must keep reading it exactly as before.

Root: `sha256:7f60b6946084c4ef35c81fea380daa2c669a1f634e8edc85b11cf79cf97a3803`
(the run manifest). 52 objects, ~230 KiB total.

**Do not regenerate this fixture.** It is a fixed point, not a snapshot of
"whatever the current code produces" -- regenerating it would defeat its
purpose of catching an unintended behavior change. If the legacy 0.1.0
contract ever needs to change on purpose, that is a decision to make
explicitly, not a side effect of updating a fixture.
