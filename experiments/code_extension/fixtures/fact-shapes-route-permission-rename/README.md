# fact-shapes-route-permission-rename

Feature: route permission. Task type: rename.

Do not publish this fixture content, including task text, hidden tests and solution patches.

All six arms share the single task.md and hidden/ directory; hidden test bytes must be identical across arms.

| Arm | Manipulated fact | Holder |
| --- | --- | --- |
| type_enforced | route_permission_rename_type_enforced | route_permission/types.ts |
| reference | route_permission_rename_reference | route_permission/policy.ts |
| name_only | route_permission_rename_name_only | route_permission/names.ts |
| sibling_only | route_permission_rename_sibling_only | route_permission/sibling.ts |
| outside_code | route_permission_rename_outside_code | route_permission/001_constraint.sql |
| existing_state | route_permission_rename_existing_state | route_permission/state.ts |

Anchor fact: route_permission_rename_anchor. Record labels accept the documented characters up to 80 characters.

Qualification is recorded under qualification/. Historical service vocabulary remains available; the new public capability checks are independently observable.

Source checkpoint: f3b3ffca43e43672ff2f58ab797d65c7532aaed8.

Excluded: network services, deployment and upstream repository history.

Adaptations: isolated public capability checks preserve the legacy service vocabulary; each arm omits its own capability and the 80-character label boundary. Hidden checks and patches remain outside repository/.
