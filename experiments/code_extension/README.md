# Code extension experiment

This package fixes the Spec 3 domain shape before any study runs. The fixture
manifest version `assay-fixture-manifest/0.3.0` declares one factor in `arm_set`
and one or more scenarios. Each scenario pins its checkpoint slice, bounded
feature request, visible requirements and named visible and hidden test groups.
Each arm records its tree, task prompt, private reference patch and negative
controls by digest, plus three retained qualification outcomes.

`arms.py` fixes the factor tags and the first run's single `baseline` arm.
Member arm ids for other factors are declared by the manifest. Before planning,
call `manifest.require_qualified()`; before dispatch, call
`shape.validate_worker_grid` with the manifest's `arm_set` as `arm_ids`.
The grid validator requires every declared subject, arm and worker repeat
exactly once and refuses qualification-smoke subjects.

This package belongs to the existing `experiments` uv project. The pilot and
two additional committed scenarios live under `fixtures/`; worker dispatch and
the evaluator are supplied by separate cohorts.

## Initial scenario roster

The first three committed subjects use the pinned oakridge-dbos checkpoint
`f3b3ffca43e43672ff2f58ab797d65c7532aaed8`. The three subject ids are
distinct from every refused qualification-smoke id (`oakridge-dbos-smoke-wf12`,
`oakridge-dbos-smoke-edit-wf13`, and `oakridge-dbos-verification-pilot-edit`).

| Subject id | Shape realized | Shared feature request | Negative control? | Pin |
| --- | --- | --- | --- | --- |
| `oakridge-dbos-context-defaults` | Cross-module extension in the qualified baseline pilot | Optional context binding defaults | No | `f3b3ffca43e43672ff2f58ab797d65c7532aaed8` |
| `oakridge-dbos-stage-pass-through` | Modular dispatch, central switch or registry, cross-module extension, and configuration-driven plugin as matched arms | Compile a `pass_through` stage whose outputs release immediately and whose materialization is scalar | No | `f3b3ffca43e43672ff2f58ab797d65c7532aaed8` |
| `oakridge-dbos-pointer-root` | Local utility edit | Accept `#` as the root JSON pointer in the shared pointer reader | Yes: the edit needs no nonlocal registration or caller tracing | `f3b3ffca43e43672ff2f58ab797d65c7532aaed8` |

The stage scenario's four trees live under `repository/<arm>/`; the pointer
control has one `repository/` tree. Each added scenario keeps its hidden groups
and per-arm patches outside those trees. `qualification/` binds the observed
image, tree, patch, and check-group digests to the baseline, reference, and
negative verdicts. The fixture suite validates every committed tree and
record. The pilot's existing qualification manifest and frozen harness remain
unchanged.
