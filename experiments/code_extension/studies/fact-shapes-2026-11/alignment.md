# Fact test alignment

Each row quotes the exact sentence in the shared task text. Each task states one
requirement over the whole service, so every manipulated fact traces to that
sentence; the anchor traces to its own sentence. A task's own feature checks
(titles `feature:...`) trace to the sentence that asks for that behavior; they are
reported but never scored as facts.

## fact-shapes-stage-additive

| Scenario | Fact test title | Task sentence |
| --- | --- | --- |
| fact-shapes-stage-additive | fact:stage_additive_type_enforced: type_enforced behavior | Reports and digests show triaged jobs under the heading "Awaiting triage". |
| fact-shapes-stage-additive | fact:stage_additive_reference: reference behavior | While a job is in triaged, its priority, owner and evidence can be changed as for any job still in progress. |
| fact-shapes-stage-additive | fact:stage_additive_name_only: name_only behavior | Triaged jobs can have escalation rules, so imported jobs left untriaged too long are escalated. |
| fact-shapes-stage-additive | fact:stage_additive_sibling_only: sibling_only behavior | Triaged jobs can be released or rejected in bulk, like single jobs. |
| fact-shapes-stage-additive | fact:stage_additive_outside_code: outside_code behavior | Archived triaged jobs are kept for at most 30 days. |
| fact-shapes-stage-additive | fact:stage_additive_existing_state: existing_state behavior | Exports always show a triaged job's current priority and owner. |
| fact-shapes-stage-additive | fact:stage_additive_anchor: anchor behavior | A job id made of letters, digits, underscores or hyphens must be accepted for stage changes up to 80 characters long, and longer or otherwise malformed job ids must be rejected. |
| fact-shapes-stage-additive | feature:stage_additive_import_triage: imported jobs start in triaged | Jobs created by an import must start in a new triaged stage instead of the initial waiting stage. |
| fact-shapes-stage-additive | feature:stage_additive_release: a triaged job is updated and released with its reason kept | A job leaves triaged in one of two ways, each with a reason that stays in the job's history: released into the initial waiting stage, or rejected by moving it to the completed stage. |
| fact-shapes-stage-additive | feature:stage_additive_reject: a rejected job is completed with its reason kept | A job leaves triaged in one of two ways, each with a reason that stays in the job's history: released into the initial waiting stage, or rejected by moving it to the completed stage. |
| fact-shapes-stage-additive | feature:stage_additive_triage_moves: no other move enters or leaves triaged | No other move into or out of triaged is allowed. |
| fact-shapes-stage-additive | feature:stage_additive_triage_not_built: triaged jobs are never picked for a build | Jobs in triaged must never be picked for a build. |

## fact-shapes-stage-rename

| Scenario | Fact test title | Task sentence |
| --- | --- | --- |
| fact-shapes-stage-rename | fact:stage_rename_type_enforced: type_enforced behavior | Everything in the service that accepts the former stage name must accept triaged instead, stored data included, and new requests must reject the former spelling. |
| fact-shapes-stage-rename | fact:stage_rename_reference: reference behavior | Everything in the service that accepts the former stage name must accept triaged instead, stored data included, and new requests must reject the former spelling. |
| fact-shapes-stage-rename | fact:stage_rename_name_only: name_only behavior | Everything in the service that accepts the former stage name must accept triaged instead, stored data included, and new requests must reject the former spelling. |
| fact-shapes-stage-rename | fact:stage_rename_sibling_only: sibling_only behavior | Everything in the service that accepts the former stage name must accept triaged instead, stored data included, and new requests must reject the former spelling. |
| fact-shapes-stage-rename | fact:stage_rename_outside_code: outside_code behavior | Everything in the service that accepts the former stage name must accept triaged instead, stored data included, and new requests must reject the former spelling. |
| fact-shapes-stage-rename | fact:stage_rename_existing_state: existing_state behavior | Everything in the service that accepts the former stage name must accept triaged instead, stored data included, and new requests must reject the former spelling. |
| fact-shapes-stage-rename | fact:stage_rename_anchor: anchor behavior | Labels containing letters, digits, underscores or hyphens must be accepted up to a length of 80 characters, and longer or otherwise malformed labels must be rejected. |

## fact-shapes-evidence-kind-additive

| Scenario | Fact test title | Task sentence |
| --- | --- | --- |
| fact-shapes-evidence-kind-additive | fact:evidence_kind_additive_type_enforced: type_enforced behavior | The new evidence kind must work everywhere in the service that the existing kinds work, stored data included. |
| fact-shapes-evidence-kind-additive | fact:evidence_kind_additive_reference: reference behavior | The new evidence kind must work everywhere in the service that the existing kinds work, stored data included. |
| fact-shapes-evidence-kind-additive | fact:evidence_kind_additive_name_only: name_only behavior | The new evidence kind must work everywhere in the service that the existing kinds work, stored data included. |
| fact-shapes-evidence-kind-additive | fact:evidence_kind_additive_sibling_only: sibling_only behavior | The new evidence kind must work everywhere in the service that the existing kinds work, stored data included. |
| fact-shapes-evidence-kind-additive | fact:evidence_kind_additive_outside_code: outside_code behavior | The new evidence kind must work everywhere in the service that the existing kinds work, stored data included. |
| fact-shapes-evidence-kind-additive | fact:evidence_kind_additive_existing_state: existing_state behavior | The new evidence kind must work everywhere in the service that the existing kinds work, stored data included. |
| fact-shapes-evidence-kind-additive | fact:evidence_kind_additive_anchor: anchor behavior | Labels containing letters, digits, underscores or hyphens must be accepted up to a length of 80 characters, and longer or otherwise malformed labels must be rejected. |

## fact-shapes-evidence-kind-rename

| Scenario | Fact test title | Task sentence |
| --- | --- | --- |
| fact-shapes-evidence-kind-rename | fact:evidence_kind_rename_type_enforced: type_enforced behavior | Everything in the service that accepts the former category name must accept attestation instead, stored data included, and new requests must reject the former spelling. |
| fact-shapes-evidence-kind-rename | fact:evidence_kind_rename_reference: reference behavior | Everything in the service that accepts the former category name must accept attestation instead, stored data included, and new requests must reject the former spelling. |
| fact-shapes-evidence-kind-rename | fact:evidence_kind_rename_name_only: name_only behavior | Everything in the service that accepts the former category name must accept attestation instead, stored data included, and new requests must reject the former spelling. |
| fact-shapes-evidence-kind-rename | fact:evidence_kind_rename_sibling_only: sibling_only behavior | Everything in the service that accepts the former category name must accept attestation instead, stored data included, and new requests must reject the former spelling. |
| fact-shapes-evidence-kind-rename | fact:evidence_kind_rename_outside_code: outside_code behavior | Everything in the service that accepts the former category name must accept attestation instead, stored data included, and new requests must reject the former spelling. |
| fact-shapes-evidence-kind-rename | fact:evidence_kind_rename_existing_state: existing_state behavior | Everything in the service that accepts the former category name must accept attestation instead, stored data included, and new requests must reject the former spelling. |
| fact-shapes-evidence-kind-rename | fact:evidence_kind_rename_anchor: anchor behavior | Labels containing letters, digits, underscores or hyphens must be accepted up to a length of 80 characters, and longer or otherwise malformed labels must be rejected. |

## fact-shapes-route-permission-additive

| Scenario | Fact test title | Task sentence |
| --- | --- | --- |
| fact-shapes-route-permission-additive | fact:route_permission_additive_type_enforced: type_enforced behavior | The new permission must work everywhere in the service that the existing permissions work, stored data included. |
| fact-shapes-route-permission-additive | fact:route_permission_additive_reference: reference behavior | The new permission must work everywhere in the service that the existing permissions work, stored data included. |
| fact-shapes-route-permission-additive | fact:route_permission_additive_name_only: name_only behavior | The new permission must work everywhere in the service that the existing permissions work, stored data included. |
| fact-shapes-route-permission-additive | fact:route_permission_additive_sibling_only: sibling_only behavior | The new permission must work everywhere in the service that the existing permissions work, stored data included. |
| fact-shapes-route-permission-additive | fact:route_permission_additive_outside_code: outside_code behavior | The new permission must work everywhere in the service that the existing permissions work, stored data included. |
| fact-shapes-route-permission-additive | fact:route_permission_additive_existing_state: existing_state behavior | The new permission must work everywhere in the service that the existing permissions work, stored data included. |
| fact-shapes-route-permission-additive | fact:route_permission_additive_anchor: anchor behavior | Labels containing letters, digits, underscores or hyphens must be accepted up to a length of 80 characters, and longer or otherwise malformed labels must be rejected. |

## fact-shapes-route-permission-rename

| Scenario | Fact test title | Task sentence |
| --- | --- | --- |
| fact-shapes-route-permission-rename | fact:route_permission_rename_type_enforced: type_enforced behavior | Everything in the service that accepts the former permission name must accept case inspect instead, stored data included, and new requests must reject the former spelling. |
| fact-shapes-route-permission-rename | fact:route_permission_rename_reference: reference behavior | Everything in the service that accepts the former permission name must accept case inspect instead, stored data included, and new requests must reject the former spelling. |
| fact-shapes-route-permission-rename | fact:route_permission_rename_name_only: name_only behavior | Everything in the service that accepts the former permission name must accept case inspect instead, stored data included, and new requests must reject the former spelling. |
| fact-shapes-route-permission-rename | fact:route_permission_rename_sibling_only: sibling_only behavior | Everything in the service that accepts the former permission name must accept case inspect instead, stored data included, and new requests must reject the former spelling. |
| fact-shapes-route-permission-rename | fact:route_permission_rename_outside_code: outside_code behavior | Everything in the service that accepts the former permission name must accept case inspect instead, stored data included, and new requests must reject the former spelling. |
| fact-shapes-route-permission-rename | fact:route_permission_rename_existing_state: existing_state behavior | Everything in the service that accepts the former permission name must accept case inspect instead, stored data included, and new requests must reject the former spelling. |
| fact-shapes-route-permission-rename | fact:route_permission_rename_anchor: anchor behavior | Labels containing letters, digits, underscores or hyphens must be accepted up to a length of 80 characters, and longer or otherwise malformed labels must be rejected. |

## Independent-holder mutant_gate rule

Replaces the single-owner rule (option A), withdrawn by the second change in
`plan-change.md` (2026-11-18). In every arm `<feature>/types.ts` declares the value
list and the edit site uses it. The arm's holder keeps its own independent copy of
the list, read only by that holder's behavior; in the other arms the same holder
derives from the type. The arms differ only in one line of that file. Except for the
direct-import policy, holder files are shared by the three features and their names
do not name a feature (round 2, `plan-change.md`): `src/presentation/labels.ts`,
`src/validation/registry.ts`, `src/services/peer.ts`,
`db/migrations/001_lookup_tables.sql`, `src/services/export_snapshots.ts` and
`src/preferences/defaults.ts`. The stage stored-state holder is the export reader's
list of stages exported from the current stored row; a job in any other stage is
exported as it was when first exported (round 3: a triaged job is reached through
import, a priority or owner change and an export, all allowed by the task, and not
through the feature's own path; the earlier build-status reader needed a running
build on a triaged job, which the task forbids).

The reference patch implements the task's feature (the same edits in every arm,
never touching a holder), and updates the type, the holder, every service literal a
rename touches, and the anchor. An omission patch is the reference with only one fact's
file left unchanged, so missing the holder still updates the type and keeps the
feature. Feature checks (titles `feature:...`) are not facts: the gate, the
qualifier's per-fact parsing and the tally read only `fact:` titles. They pass on
every reference and fail on the start tree. The shared
hidden group runs in full. The mutant gate scores the arm's manipulated fact and the
scenario anchor: the reference must pass both, and each omission must fail only its
own scored fact. Both regression groups must pass. Other arms' titles are not scored
for an arm. They pass on every reference and on every omission except two. The
direct-import policy sits on the primary path, so hidden checks that call the edit
operation with the new value fail with it. The database CHECK constrains a lookup
table that other stored data references, so hidden checks that store such a record
with the new value fail with it: for evidence kinds and permissions that is the
evidence and grant records (so their stored-state checks fail too). The stage lookup
table gates only the per-stage retention settings, not stored jobs (operator decision,
option b, 2026-11-19), so a stage feature can store jobs in the new stage while the
CHECK is stale, and the stage outside-code check stores a retention setting for the
new stage through the maintenance service. Open: in the route-permission rename the
outside-code omission also fails visible checks, because every reader holds the
renamed read permission, so that cell cannot meet the regression rule as written.
The type-enforced
omission fails type-checking, confined to the label-map holder, and is accepted only
through holder-confined preflight classification. Every
control is replayed twice in fresh sandboxes.

Round 5 (stage only) makes the stage holders implicit. `stage/types.ts` declares a
`stageTraits` map the compiler requires for every stage (heading, open, code,
retention days, route, next stages). In every version a holder reads its trait, except
the version's own holder, which decides by stage position, by numeric stage codes in a
SQL CHECK, or (control) by a compiler-checked map of display headings, and names no
stage. The stage-additive task states one rule per holder for the new stage; each fact
maps to that sentence. The outside-code version has no typed retention limit, so its
CHECK alone enforces the triaged limit. The audit finds implicit holders by trait reads
and by positional or coded encodings. Stage-rename is not yet redesigned: a rename keeps
a stage's position, so its positional omissions do not fail their facts.

Round 4 doubled the application code with seven service features (comments, audit
queries, tags and saved searches, project settings and usage, escalation rules,
scheduled digests, notifications and webhooks) without adding a holder. New code
derives every stage, evidence-kind or permission list from the feature's type, names
no value that a rename task renames (read checks use `readAccess` from
`src/domain/access_levels.ts`, the first declared permission), and adds no foreign key
or CHECK on a vocabulary column. Some new reports read the existing label helpers. The
holder audit is clean on the base and on every arm.

The baseline omits the requested change and the 80-character label boundary; the
anchor omission keeps the limit at 79. Visible checks that pass through a holder use
values every arm keeps under the same spelling (for example `active`, `image`,
`case_write`) and an unreserved sentinel for unsupported values, so a missed holder
never fails a visible check. Lifecycle tests use the existing build,
evidence-default and permission-default service operations. Additive
duplicate-state controls cache a second copy that stops following changes to the
original source. Typed fact tests also compile a caller of the existing public edit
operation and of the label map.

## Operator approvals

The operator authorized scope expansion and fixture repair: “scope - allowed;
conflict - fix fixtures”. The fixture.py registration and qualify.py integration
are included in that expansion. Typecheck preflight was confirmed (“typecheck -
confirmed”), and Docker qualification was authorized (“qualification - authorized”).
The operator confirmed the computed caps (“caps confirmed”): 61 USD for the pilot
and 1267 USD for the main study, including one probe per plan; per-attempt caps
are 2 USD for Sol, 4 USD for Argon, and 1 USD for the mid-tier route.
The publication hold was replaced with “pub - jsut commit to assay like nomral”,
followed by “you are allowed to push to the repo and open a PR”.
The current assessment requests option A. In response to the explicit questions
about retaining the 79-to-80 anchor boundary and adapting conflicting visible
assertions, the operator replied “approved”. These approvals govern this revision.

## Qualification scheduling

Full-path arm replays use serial arm scheduling. Earlier concurrent replays of
a preliminary helper-based version disagreed; logs were retained and diagnostic
output was added to qualify.py. The final existing-public-API material is fully
requalified and verified with unchanged acceptance rules and fresh-run counts.

## Independent typed-fact control

Each type-enforced arm also replays `type-without-required-feature.patch` twice.
This control starts from the manipulated-fact omission and casts the label map's
unchanged literal (`as unknown as Record<...>`), so the repository type-checks while
the new value still has no label. The anchor fix remains. The gate requires preflight
to pass, both regression groups to pass, the typed fact title to fail, and the anchor
title to pass. Preflight classification cannot satisfy this independent control. Its
evidence includes the complete control patch and both runs, demonstrating that the
hidden check detects the missing label at run time and not only through the
compiler. The holder-only preflight omission remains as a separate check.

## Follow-up migration compatibility

The outside-code positive controls restore the base migration, widen the vocabulary
in a follow-up migration numbered after every existing migration (recreating only
that feature's table from the shared base migration) and create an index in the next
one. The service applies every file in `db/migrations/` in filename order,
so a new migration and an edit to the base migration both pass. Business tables
reference the constrained lookup tables and seeding skips a value the CHECK refuses,
so with a stale CHECK the service starts but storing a record with the new value
fails its foreign key; the outside-code check stores and reads back such a record
through the service.
Migration discovery checks the initial table definitions without requiring later
migrations to repeat those definitions. Frozen fixture copies, qualification evidence
and cohort pins must be regenerated before this source change is used for a study run.
