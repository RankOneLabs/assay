# fact-shapes-stage-rename

Feature: stage. Task type: rename.

Do not publish this fixture content, including task text, hidden tests and solution patches.

All six arms share the single task.md and hidden/ directory; hidden test bytes must be identical across arms.

| Arm | Manipulated fact | Holder |
| --- | --- | --- |
| type_enforced | stage_rename_type_enforced | stage/types.ts |
| reference | stage_rename_reference | stage/policy.ts |
| name_only | stage_rename_name_only | stage/names.ts |
| sibling_only | stage_rename_sibling_only | stage/sibling.ts |
| outside_code | stage_rename_outside_code | stage/001_constraint.sql |
| existing_state | stage_rename_existing_state | stage/state.ts |

Anchor fact: stage_rename_anchor. Record labels accept the documented characters up to 80 characters.

Qualification is recorded under qualification/. Public operations derive their vocabulary from the single selected owner. Only this arm’s manipulated fact and the scenario anchor are scored by the mutant gate.

Source checkpoint: f3b3ffca43e43672ff2f58ab797d65c7532aaed8.

Excluded: network services, deployment and upstream repository history.

Adaptations: the variant-generator owner placement is restored; visible unsupported-value assertions use an unreserved sentinel and canonical-value assertions follow the current owner. The baseline omits the requested vocabulary value and the 80-character label boundary. Hidden checks and patches remain outside repository/.
