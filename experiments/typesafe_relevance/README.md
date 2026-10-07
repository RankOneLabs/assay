# Typesafe relevance study

The reference implementation for the Typesafe relevance study:

- the catalogue loader computes a canonical-JSON version;
- `state.build_state` is the pure state projection consumers copy;
- `mappings` contains the pure decision functions.

The study population is not distributed with this repository. To reproduce the
provider calls, supply the two population JSONL files, check that their digest
matches the one recorded in the plan, and invoke `run_primary` with them.
`TYPESAFE_API_KEY` must be set.

Tests that check the published reproduction bundles skip unless
`ASSAY_RUN_RECEIPTS` points at a checkout containing them.

**Result:** Typesafe did not meet the registered adoption rule. The catalogue
and mappings may be reused for reproducibility, but this result does not support
enabling a Typesafe backend.
