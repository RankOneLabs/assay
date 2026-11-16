# fact-shapes-stage-additive

Feature: stage. Task type: additive.

Do not publish this fixture content, including task text, hidden tests and solution patches.

All six arms share the single task.md and hidden/ directory; hidden test bytes must be identical across arms.

| Arm | Manipulated fact | Holder |
| --- | --- | --- |
| type_enforced | stage_additive_type_enforced | stage/types.ts |
| reference | stage_additive_reference | stage/policy.ts |
| name_only | stage_additive_name_only | stage/names.ts |
| sibling_only | stage_additive_sibling_only | stage/sibling.ts |
| outside_code | stage_additive_outside_code | stage/001_constraint.sql |
| existing_state | stage_additive_existing_state | stage/state.ts |

Anchor fact: stage_additive_anchor. Record labels accept the documented characters up to 120 characters.

Qualification is pending; this fixture is not yet runnable study material.
