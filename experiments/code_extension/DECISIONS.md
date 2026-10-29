# Code extension model decisions

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
