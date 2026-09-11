# Review remediation and release gates

The previous implementation is a scaffold, not a completed v1. This plan closes
the reviewed failures before any pull request is marked ready.

## Work and ownership

1. PAA contracts: make the numeric fixture valid against a real task declaration,
   test companion-schema constraints and semantic identity, preserve canonical
   content addresses, and rerun package and conformance checks.
2. Domain and verification: validate identifiers and content references, make
   coordinate identity unambiguous, validate snapshot and plan consistency,
   generate complete wire schemas, and verify all manifest records and local
   reference closure. Export only the manifest's closure and reject inserted,
   missing, substituted, or malformed objects in an exported bundle.
3. Execution: bind actual adapter configurations to authorized declarations;
   preserve Jig failures and exact inputs; use run-scoped record identities and
   actual declaration metadata and timestamps; preserve successful and failed
   attempt accounting. Stop scheduling after persistence failure, settle active
   tasks, and return a typed run failure carrying durable progress.
4. Reporting: consume pinned complete manifests and exact record selections,
   reject duplicates and subject drift, aggregate evaluator then worker repeats,
   and report missingness before paired effects. Support scalar, ordinal and
   classification outcomes with deterministic subject-level inference, fixed
   paired-v2 thresholds, and an explicit Holm family. Persist report artifacts
   so offline verification can recompute them.
5. Integration: supply the local consistency investigation outside the core,
   exercise both repeat axes and failures/exclusions without paid calls, and
   test the built package and standalone install.
6. Release: review and commit upstream changes on topic branches first, replace
   Assay's sibling-directory dependencies with those exact Git commits, verify
   an isolated checkout, then branch/commit/push Assay and open linked PRs.

The primary agent owns integration, reviews every delegate's diff, reproduces
the previously failing cases, and decides whether the release gate passes.
Agents do not independently commit or publish.

## Acceptance evidence

- A returned Jig error cannot yield successful execution evidence.
- Configuration, snapshot, scheduling, or evaluator drift makes zero calls.
- Distinct runs have distinct terminal record identities and real timestamps.
- A failed store stops new scheduling and yields a typed, inspectable failure.
- Failed attempts retain trace, usage and cost coverage; missing is not zero.
- Arbitrary JSON, wrong coordinates, duplicate evidence, broken references,
  invalid PAA records and bundle insertions fail verification specifically.
- Duplicating a verdict cannot change a report; subject digests govern pairing.
- Scalar golden cases at n=2,9,10, ordinal ties/order and classification metrics
  are checked. Recomputing from a pinned report config yields identical bytes.
- PAA positive fixtures pass structural, companion and semantic checks.
- Jig, PAA and Assay checks pass; a fresh Assay checkout requires no siblings.

Any remaining v1 limitation must be explicit in the handoff and PR description;
passing a small test suite does not waive a missing acceptance requirement.

## Implemented boundaries

The local consistency investigation and full offline acceptance pipeline are
implemented, but a production coding-agent worker and paid experiment are not
included. Callers supply a repository/task adapter and an optional ambiguity
judge; the bundled Jig adapter accepts explicitly materialized prompt strings.
Preparation stages and component-level cost aggregation fail explicitly.
These are documented integration boundaries, not claims of full experimental
or producer-attestation support.

The final independent review also added subject-declaration binding across
runs, strict operating-attempt provenance, categorical aggregation validation,
and required numeric optimization direction. Schema validators are reused
within a manifest, keeping offline recomputation practical without weakening
validation.
