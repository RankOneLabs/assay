# pier_packages fixtures

Used by `tests/test_pier_secrecy.py` to prove that `assay.pier_packaging`
never leaks experimental information the model must not see. Each directory
holds a unique sentinel string; the secrecy test asserts every sentinel from
every directory *except* `arm_a/` is absent from a package built from
`arm_a/`.

- `arm_a/` — the selected arm's repository. Its own sentinel
  (`SENTINEL_ARM_A_VISIBLE_1a2b`) is expected to appear in the built package.
- `other_arm/` — a different arm's repository
  (`SENTINEL_OTHER_ARM_HIDDEN_3c4d`). Must never appear: packaging is called
  once per selected arm, and never reads another arm's files.
- `hidden_tests/` — held-out test fixtures (`SENTINEL_HIDDEN_TEST_5e6f`).
  Not a repository file; must never enter the package.
- `evaluator/` — evaluator rubric/reference data
  (`SENTINEL_EVALUATOR_7g8h`). Evaluation is out of scope for the model.
- `object_metadata/` — a stand-in for object-store bookkeeping
  (`SENTINEL_OBJECT_METADATA_9i0j`). Digests and store paths are Assay's
  concern, never the model's.
