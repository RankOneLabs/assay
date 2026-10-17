# Verification pilot foundation

The pilot studies verification after a contributor handoff. Four fixed G3 type
renames and the T1/T2/T3 texts and submission shapes live in `inputs.py`.
`fixtures.py` derives the use sites and three-way ownership from the pinned
62-file Oakridge slice at `raw/repo/`. The slice is inert input data; generated
subject workspaces add one old-spelling remnant and two historical decoy files.

The fixture produces 16 base subjects: for each rename, three planted owners
and one clean control. The 12 planted subjects run in native and quoted
presentation, making 24 active sessions. `study.compile_pilot_plan()` builds
the Assay snapshot and active coordinates from those records. One
`pilot_judge` evaluator is declared per session. The pinned
`PILOT_TOOLS_SHA256` still identifies the existing six-tool Pier surface.

Run `pytest experiments/verification_pilot/tests` for pilot checks. The
model-free scripted command and the live qualification gate are documented in
`SMOKE.md`. Results must remain marked pending until a qualified live route
has reviewed records.
