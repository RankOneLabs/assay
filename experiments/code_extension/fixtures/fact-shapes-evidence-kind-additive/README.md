# fact-shapes-evidence-kind-additive

Feature: evidence kind. Task type: additive.

Do not publish this fixture content, including task text, hidden tests and solution patches.

All six arms share the single task.md and hidden/ directory; hidden test bytes must be identical across arms.

| Arm | Manipulated fact | Holder |
| --- | --- | --- |
| type_enforced | evidence_kind_additive_type_enforced | evidence_kind/types.ts |
| reference | evidence_kind_additive_reference | evidence_kind/policy.ts |
| name_only | evidence_kind_additive_name_only | evidence_kind/names.ts |
| sibling_only | evidence_kind_additive_sibling_only | evidence_kind/sibling.ts |
| outside_code | evidence_kind_additive_outside_code | evidence_kind/001_constraint.sql |
| existing_state | evidence_kind_additive_existing_state | evidence_kind/state.ts |

Anchor fact: evidence_kind_additive_anchor. Record labels accept the documented characters up to 80 characters.

Qualification is recorded under qualification/. Public operations derive their vocabulary from the single selected owner. Only this arm’s manipulated fact and the scenario anchor are scored by the mutant gate.

Source checkpoint: f3b3ffca43e43672ff2f58ab797d65c7532aaed8.

Excluded: network services, deployment and upstream repository history.

Adaptations: the variant-generator owner placement is restored; visible unsupported-value assertions use an unreserved sentinel and canonical-value assertions follow the current owner. The baseline omits the requested vocabulary value and the 80-character label boundary. Hidden checks and patches remain outside repository/.
