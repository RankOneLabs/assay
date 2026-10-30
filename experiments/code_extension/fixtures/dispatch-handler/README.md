# Dispatch-handler extension scenario

Subject `oakridge-dbos-dispatch-handler` is one baseline arm adapted from the
oakridge-dbos checkpoint `f3b3ffca43e43672ff2f58ab797d65c7532aaed8`.
The task freezes the `projectWorkStartedEvent`, `WorkStartedRunEventPayload`,
and `projectRunEvent` API names. The existing event projector is the dispatcher:
gate and pull-request branches already route to their specialized behavior.
The new handler must validate work-started identity and be reached through that
dispatcher. `repository/` alone is worker-visible. Hidden groups and the
operator-authored patches are sibling directories, outside the shipped tree.

## Provenance and extraction

The source is the private oakridge monorepo at the immutable commit above. The
initial archive invocation used for the pilot slice, reused here, is:

```sh
git -C /home/steve/codes/rol/oakridge archive f3b3ffca43e43672ff2f58ab797d65c7532aaed8 oakridge-dbos/src/domain oakridge-dbos/src/decision oakridge-dbos/src/compiler oakridge-dbos/src/validation oakridge-dbos/src/seed/dev-flow-v14.ts oakridge-dbos/tests workflow-config/definitions/dev_flow_v11.json workflow-config/definitions/dev_flow_v14.json workflow-config/prompts/dev-flow
```

Selection rules: include the pilot's self-contained `src/domain/`,
`src/decision/`, `src/compiler/`, `src/validation/`, `src/seed/dev-flow-v14.ts`,
the two selected workflow definitions, selected prompts, and the 11 visible
test files. Copy the pilot's frozen package files and strict TypeScript config.
The pin contains no standalone license file for the private oakridge-dbos
source; the locked third-party package notices are MIT or Apache-2.0 in
`package-lock.json`. This is an internal research fixture, not a redistribution
of an independently licensed package.

The start tree has 62 files and 348,954 UTF-8 bytes, below the 200-file and
1,000,000-byte limits. Its canonical tree digest is
`sha256:0cda9de2bc67a3f2cacd28dbabb527126a1a52db63c536e50d981f8b0606d3fb`.
The `package-lock.json` digest is
`sha256:45d8352b7c5c9cfd47b67f9e146f7d9a94c360c7a7150db2c388b30ee4894df7`.
The sidecar repeats these provenance hashes so the loader can reject drift.

## Excluded areas and adaptations

Excluded from the pilot and this scenario are `oakridge-dbos/src/storage/`,
`src/http/`, `src/runtime/`, `src/workflows/`, `src/adapters/`, the service
entry points, and unselected tests, including tests requiring Postgres or
DBOS. Their dependencies are outside this bounded task. The selected source
files moved under `repository/src/`; selected tests moved to
`repository/tests/visible/` with relative imports adjusted. The seed config
URL and flattened `tsconfig.json` follow the pilot adaptation. The fixed
package files come from the Assay runtime toolchain, not from the upstream
monorepo's full service package. No production behavior was changed in the
start tree. The hidden work-started checks and three qualification patches
were authored locally and stay outside `repository/`.

The sidecar declares `src/domain/` as the writable directory because the
production repository agent accepts directory prefixes. The task restricts
the requested implementation to `src/domain/run-event.ts`; every held patch
touches only that file. Visible tests, `package.json`, `package-lock.json`, and
`tsconfig.json` are explicitly protected. The sidecar's
requirements-to-tests table links every private assertion to a public task
requirement or an existing behavior. It also records the intent and expected
unrelated group results for both incomplete patches.

## Qualification

Run from `experiments/`:

```sh
uv run python -m code_extension.qualify --scenario dispatch-handler --image assay-code-extension:run-bfb5dd7d9189a983 --verify-committed
```

The observed image digest is
`sha256:a63b8377bf057a7d888f279c42b54ff904c6b1353af509a5016573ab7ac2cdf3`.
The three canonical qualification records under `qualification/evidence/`
retain only group verdicts and causes. The five additional controls are
content-addressed under `qualification/gates/`: a no-op run, twice-reproduced
start/reference/incomplete controls in fresh evaluator sandboxes, a scripted
`write_file` and `submit_output` reference submission graded by the independent
evaluator, an access probe through all five exposed tools, and an extension
leak scan of the worker-visible tree, rendered task and observed tool output.
The manifest binds the frozen task, tree, groups, patches and three records;
the versioned sidecar binds the remaining gate evidence. No control makes a
model request. The reference and incomplete patches are evaluator controls,
not model-generated observations.

The full `experiments/` pytest suite also requires the pinned Node `jscpd`
tool for the separate `code_metrics` tests. Provision that tool before using
the full suite as a checkout-wide check; it is not part of this fixture's
TypeScript runtime image.
