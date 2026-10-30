# Code extension model decisions

## Dispatch-handler WP1 fixture and gate

- `dispatch-handler` is the only new scenario in this cohort. Its subject id is
  `oakridge-dbos-dispatch-handler`, distinct from the three refused smoke ids.
  The three existing committed subjects and their evidence remain unchanged.
- `fixtures.py` loads the `assay-extension-scenario-sidecar/0.1.0` record using
  the core types from `contract.py`. The study-local extension carries tool
  instructions, the declared outcome of every unrelated check for each
  incomplete patch, and provenance: extraction invocation and rules, license
  notices, local adaptations, tree size and digest, and dependency lock
  digests. The existing sidecar fields carry writable scope, protected assets,
  requirements-to-tests links, patch intent and five gate-evidence digests.
  The loader reads actual patch headers and refuses undeclared or protected
  paths; the 0.3.0 manifest schema is unchanged.
- `qualify.py` has one model-free entry point with required `--scenario` and
  `--image`. It defaults evidence and manifest paths beneath that scenario's
  qualification directory. It inspects the image and binds its observed
  sha256 digest, never the mutable tag. Feature failure counts only when both
  regression groups pass, the feature group fails with `group_failure`, and
  a separate `diagnose_candidate` replay names a test that ran. Only a boolean
  gate decision is retained; test names and output are not retained.
- Three incomplete patches exercise a missing dispatcher registration, omitted
  identity validation, and missing public payload type export. They compile
  before hidden checks and preserve unrelated regression groups. A no-op
  candidate and every start/reference/incomplete control run
  twice in fresh evaluator sandboxes. The scripted worker applies the known
  patch through `ExtensionBridgeClient`, `write_file` and `submit_output`; the
  independent evaluator checks the captured candidate. The bridge resolves
  the scenario sidecar by subject and enforces `src/domain/` for dispatch-handler,
  so the protected visible tests are outside the writable scope. Existing
  committed subjects keep their prior scope until they gain sidecars. Scripted
  turns replace model calls while the bridge still supplies its production
  system prompt, bounds, tools, scope and trial sealing.
- `probe.py` scripts attempts through all five baseline tools, including shell
  and symlink paths. `leaks.py` uses the shared `scan_text` scanner with
  extension-specific markers over the agent-visible tree, rendered prompt and
  observed tool output. Per-attempt results and scanner hits are retained in
  `fixtures/dispatch-handler/qualification/gates/`, with their digests in the
  sidecar. These are operator-authored controls, not model observations.
- The experiments CI job sets `ASSAY_REQUIRE_DOCKER=1` to require the daemon,
  but it does not provision the dispatch-handler fixture's exact image. Its
  replay test skips only when that image is absent; setting
  `ASSAY_REQUIRE_EXTENSION_IMAGE=1` makes image absence a failure on a
  qualification machine. The committed records and gate files, plus exact
  replay on the provisioned machine, remain the qualification evidence.

## ce-v1 contract freeze

- `assay-extension-scenario-sidecar/0.1.0` holds the six missing contracts:
  per-scenario writable implementation scope; declared protected test,
  dependency and configuration files; requirements-to-tests links; reference
  and incomplete patch inventory with intent; and refs for leak-scan,
  access-probe, no-op, scripted-submission and double-reproduction evidence.
  The 0.3.0 fixture manifest and its predecessors remain fixed.
- `ce-v1` version `1.0.0` has one initial user turn, with feature request,
  workspace and test instructions, declared scope and budget. Its system
  prompt, rendered task witness, ordered extension tool schemas and submission
  schema have literal digest pins. Scenario-specific rendered task digests are
  recorded at delivery.
- Calibration defaults are timeout_s 900.0, max_turns 60,
  max_output_tokens 8192 and max_tool_output_bytes 32768. Model context limit
  and request timeout are explicit. The 120 per-cell tool-call ceiling is
  unavailable because the loop enforces such ceilings only in pilot_mode,
  which is incompatible with extension_mode. Requested and provider-reported
  sampling values are separate and unset by default.
- The operator authorized the lockstep image-side config update and
  requalification. `assay-code-extension:ce-v1-bounds` was rebuilt from the
  updated config and inspected as
  `sha256:d0da319d2e141415c1c41ccea44983e8986944e5ae45b53652a9c104c462c4ee`.
  The pilot, pointer-root and stage-pass-through fixtures were requalified;
  their baseline, reference and negative verdicts matched the old records.

- The operator will decide whether the final committed set contains three or
  four scenarios after reviewing the baseline pilot. The scenario-set cohort
  targets three total, including the pilot, and will not add an unqualified
  fourth merely to reach a count.

## Study authorization and evaluation

- `study.check_fixture` validates the 0.3.0 manifest against operator-held
  per-arm trees and content-addressed test groups before planning. It refuses
  image or routing drift, an unqualified arm, tree drift, hidden checks in a
  shipped tree, and visible tests that differ across arms. It also re-reads
  the three retained qualification records and binds each outcome to its
  scenario, arm, image and tree.
- A study plan uses scenarios as subjects and the manifest's single arm-set
  factor as its arm dimension. Every arm declares `subject-rotated-v1` in its
  conditions, and `shape.validate_worker_grid` runs before plan bytes are
  returned for authorization. The shared planner treats this schedule as a
  no-op for the committed single-arm baseline pilot, so the same authorized
  schedule covers both pilot and multi-arm study runs.
- `evaluation.CellEvaluator` reads its arm and subject from the cell, its
  baseline from the realization, and its baseline digest from worker evidence.
  A mismatch is a named `unavailable` verdict. It passes only the frozen
  visible, hidden regression and new-behavior groups to the runner and retains
  status and cause per group, never test output. Diagnosis remains a separate
  replay.
- `dispatch.cell_idempotency_key` is imported by the extension bridge for the
  stable run-and-coordinate key, so a lost response reuses the same
  Smithers job at each turn. The core run manifest records unsettled and
  unevaluated coordinates as incomplete; study execution uses that manifest.
- The 0.3.0 manifest is a new wire version. The 0.1.0 and 0.2.0 models and
  their published schemas remain unchanged.
- One discriminated arm set declares the factor for the whole manifest. The
  first run has one `baseline` arm; other factors declare their member ids per
  manifest. `code_shape` uses distinct trees per arm. All other factors share a
  tree per scenario. Only `handoff_detail` may vary task prompts.
- Qualification belongs to each arm and consists of baseline passing, feature
  checks failing before the change and the reference patch passing. Each result
  binds its retained record digest. Planning requires every arm to qualify.
- The reference patch is a qualification asset by digest. An acceptance harness
  will be the evaluator oracle in a later cohort.
- Every qualification-smoke subject id is refused by the grid validator.
  The extension image has route-specific typed ceilings in `settings.py` and
  the image-side `code_extension.yaml`. The served contexts are 32,768 tokens
  for `qwen-coder-32b` and 131,072 for `qwen3.6-27b`, as recorded by the
  existing fleet notes. The coder ceilings use the measured, qualified Part 1
  envelope at the same served context (`workflow_edit/SMOKE.md`); the Qwen3.6
  ceilings use the verification pilot's measured source-slice envelope at its
  served context (`verification_pilot/settings.py`). Neither route uses a
  token-count formula to set byte ceilings.
- `EXTENSION_TOOLS` replaces only `submit_output` on a deep copy of `TOOLS`.
  The new fields are retained in `result.json` submissions. They do not alter
  the trial envelope or the evaluator's candidate inputs, so the three
  `assay-pier-trial/0.4.0` wire copies do not advance.
- The authorized extension model matrix is declared in `bridge.py`; a route
  outside it raises `UnauthorizedModelRoute` in `create`, which `PierAdapter`
  records as a typed cell failure before any model request. The image digest is
  observed with `docker image inspect` when the cell is created.
- Code-intelligence delivery calls the existing provider with fixture hidden
  check paths excluded. The manifest, preloaded summary, and every declared
  preflight query result are scanned before index bytes reach a sandbox.
  `index_agent_readable` is recorded as declared operator policy. `arms.py`
  declares the study's `/cache/codeintel` mount and its per-arm mapping:
  baseline uses baseline/tool, symbols uses symbols/tool, and relationships
  uses relationships/preloaded. The bridge refuses a different delivery
  before dispatch; relationships/tool is never an authorized arm.
- The extension evaluator is a later cohort. Once it exists, its regression
  test must compare evaluator configuration and group commands byte for byte
  across code-intelligence arms, in addition to the shared prompt assertion.
- The image digest is obtained with `docker image inspect --format '{{.Id}}'`
  after building. After updating the ceilings and submission validation,
  `assay-code-extension:run-bfb5dd7d9189a983` inspected as
  `sha256:a63b8377bf057a7d888f279c42b54ff904c6b1353af509a5016573ab7ac2cdf3`.
  Fixture qualification must bind this observed digest, never the mutable tag.

The extension requalification smoke ran one zero-paid repository-agent cell on
each authorized route against that final image. Each read `src/math.py`, added
`double(value: int) -> int`, ran a read-only Python AST check, and submitted.
Both settled as candidates without a conversation truncation, tool-output
truncation, or output cutoff. The observed extension tool schema was 2,119
bytes on both routes. The cell-level measurements were:

| Route | Requests | Peak message bytes | Final conversation bytes | Peak tool return bytes | Peak prompt tokens | Peak completion tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| qwen-coder-32b | 3 | 2,749 | 3,270 | 966 | 1,186 | 100 |
| qwen3.6-27b | 4 | 3,268 | 3,867 | 966 | 1,514 | 123 |

This small smoke verifies the final image, route bindings, extension tool
surface, and that these live cells fit inside the named envelopes. It does
not saturate the byte ceilings; the larger ceilings retain the already
qualified Part 1 and pilot headroom. No extension fixture was qualified.

# Pilot qualification decisions

- The first study subject is `oakridge-dbos-context-defaults`, a pinned slice of
  oakridge-dbos at `f3b3ffca43e43672ff2f58ab797d65c7532aaed8`. It promotes
  the bounded context-binding request exercised by the workflow-edit smoke into
  the extension study's committed pilot. The pilot is a study subject and is not
  added to `SMOKE_SUBJECT_IDS`. Its README records the archive invocation,
  path mapping, exclusions, and mechanical adaptations.
- `fixture.py` loads only committed content. Visible tests are frozen from
  `repository/tests/visible/`; the held-out regression and feature groups and
  both patches live outside `repository/`. The negative patch is deliberately
  incomplete: it accepts and types defaults but omits resolution and launch
  requirement behavior.
- `qualify.py` runs `baseline_passes`, `feature_fails`, and `reference_passes`
  separately through `DockerWorkflowRunner` in the image inspected as
  `sha256:a63b8377bf057a7d888f279c42b54ff904c6b1353af509a5016573ab7ac2cdf3`.
  The runner restores visible tests before typecheck and bun build, then copies
  the private groups and runs all three with `--network=none` and `--pull=never`.
  The reference patch is used only for `reference_passes`; it is not an evaluator
  oracle. Each retained canonical JSON record contains only group verdicts and
  causes, and its digest appears in the 0.3.0 manifest. Assembly re-reads and
  validates the records and the current image digest and reads the routing file
  at assembly time. It raises on a dead feature group or any other unqualified
  arm, so no unqualified manifest is returned.
- The committed baseline and feature checks observed visible regression and
  hidden regression passing and new behavior failing. The committed reference
  check observed all three groups passing. Repeating qualification produced
  byte-identical retained records. `diagnose.py` replays a recorded failed group
  in the same image to name failing tests or the first typecheck errors. It has
  no path that writes a verdict or evidence record.

## Measurement and reporting

- The classification first pass is exhaustive over the typed Pier candidate
  and infrastructure causes. It distinguishes invalid or incomplete work from
  valid but wrong work, then requires an attributed, trace-bound operator
  judgment for the six interpretive categories.
- A passing attempt has no failure category. An unstarted cell cannot have
  patch or trace bytes; its row retains the run-manifest reference and absent
  artifact references. Settled failures expose any partial patch and trajectory
  retained by the bridge.
- The ledger counts planned cells as attempted, submitted candidate cells as
  completed, and externally correct cells as passed. Self-report remains a
  separate measure. Missing judgments for settled candidate failures stop
  ledger construction rather than silently dropping their rows.
- The committed report is a descriptive template until run evidence is
  committed. Its fixture roster is read from the three committed qualification
  manifests. No run observations or inferential statistics are invented.
- Code metrics reuse the sibling study's locked TypeScript toolchain and the
  existing `assay.code_metrics` snapshot/compare API. Installing locked tools
  is an explicit preparation step; measurement is offline.
