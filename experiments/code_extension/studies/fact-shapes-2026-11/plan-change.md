# fact-shapes-2026-11: plan change

Filed 2026-11-15, before any run of this study. The cell table must be written
and reviewed before the base service is built.

The tasks change because GPT-6.1 Sol reached the ceiling: it passed **57 of 57**
submitted attempts in the matched-task study (57 submitted of 60 dispatched;
[results](../matched-tasks-2026-11/results.md)) and **11 of 11** in the code
extension library's one-attempt-per-task calibration, including a 2-task recheck
([study plan](../scenario-library/study-plan.md)). Those task sets cannot rank
shapes.

The three changes are:

1. **intent-only** task text: no keys, files or classes are named.
2. **per-fact** scoring: one hidden test group per required fact.
3. **rename-only restructuring**: every restructuring task renames an existing
   stage, evidence kind or route permission.

The pilot's third-fact trigger is fixed in advance: if Sol misses
at most 1 of its 10 non-control manipulated facts in the pilot, a third required
fact is added through a further written plan change before the full run.
The pilot has 12 Sol attempts, 2 per shape; the 2 type_enforced control attempts
are excluded from these 10 manipulated facts.

The reviewed cell table is rendered from the single typed source
`code_extension/fact_shapes/cells.py`. Later base-fixture, generator, scoring and
tally cohorts import that source and never re-declare the table.
