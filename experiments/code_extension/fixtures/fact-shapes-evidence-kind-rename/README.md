# fact-shapes-evidence-kind-rename

Feature: evidence kind. Task type: rename.

Do not publish this fixture content, including task text, hidden tests and solution patches.

All six arms share the single task.md and hidden/ directory; hidden test bytes must be identical across arms.

| Arm | Manipulated fact | Holder |
| --- | --- | --- |
| type_enforced | evidence_kind_rename_type_enforced | evidence_kind/types.ts |
| reference | evidence_kind_rename_reference | evidence_kind/policy.ts |
| name_only | evidence_kind_rename_name_only | evidence_kind/names.ts |
| sibling_only | evidence_kind_rename_sibling_only | evidence_kind/sibling.ts |
| outside_code | evidence_kind_rename_outside_code | evidence_kind/001_constraint.sql |
| existing_state | evidence_kind_rename_existing_state | evidence_kind/state.ts |

Anchor fact: evidence_kind_rename_anchor. Record labels accept the documented characters up to 120 characters.

Qualification is pending; this fixture is not yet runnable study material.
