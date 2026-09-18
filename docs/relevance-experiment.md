# Typesafe relevance primary study

The reference implementation lives in `assay.investigations.relevance`. Its
catalogue loader computes a canonical-JSON version, `state.build_state` is the pure
state projection copied by consumers, and `mappings` contains the pure decision
functions. The primary report and answer-only reproduction bundle are under
`evidence/typesafe-relevance-primary-2026-09/`.

The private population is not repository material. To reproduce provider calls,
export the two pinned Scout snapshots, exclude the agent-evals `GAIA` route, verify
the population digest recorded in the plan, and invoke `run_primary` with the two
JSONL files. The command requires `TYPESAFE_API_KEY`; install the `typesafe` extra.

The 2026-09-18 report is negative: Typesafe did not meet the registered adoption
rule. Consumers may adopt the catalogue and mappings for reproducibility, but must
not enable a Typesafe backend on the strength of this report.
