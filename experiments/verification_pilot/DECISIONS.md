# Verification pilot decisions

The fixed inputs live in `inputs.py`. G3 uses four type renames:
`StageInstanceId` → `StageRunId`, `WorkflowRunId` →
`WorkflowExecutionId`, `RunUnitId` → `ExecutionUnitId`, and
`WorkOrderId` → `TaskOrderId`. The pilot system prompt, three turn texts, and
submission shapes are named and typed there. The pinned Pier tool digest stays
unchanged because the six-tool surface and its T1 versus review submission
fields have not changed.

The raw Oakridge repository slice lives in `raw/repo/`. Its README records
provenance and makes clear that it is inert input data. `fixtures.py` reads the
slice, matches symbols at whole-word boundaries, derives use sites, and assigns
three owners in deterministic sorted round-robin order. At the pinned slice the
file counts are 20, 18, 10, and 8 respectively; the new spellings occur in no
file. Even the eight-file rename gives every owner at least two files.

G6 plants `CHANGELOG.md` and `docs/migration.md` as historical decoys per
subject. They are absent from the raw slice. For each rename, the derived
population has one planted remnant in each of the three owner shares and one
clean control, yielding 16 base subjects. The 12 planted subjects each receive
native and quoted T1 presentation, yielding 24 sessions. The clean controls
remain in the declared population and are excluded from the active session
shard. `study.py` obtains the subjects and active coordinates from these fixture
records, with one worker execution per session.

G15 declares one evaluator, `pilot_judge`, per active session. The prior
scripted grid of separate per-turn and per-owner evaluator declarations is
retired. The scripted run verifies the shape and sealed trace path; it is not
a measured model result. The published study has pending results only, so
replacing the old design does not erase a measured finding.

The existing pilot tool digest, route bounds, and worker loop remain pinned.
Any later loop or measurement changes belong to later cohorts. The
qualification smoke must be reviewed before live results are interpreted.
