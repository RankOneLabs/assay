# Code extension study measurement and reporting

The study treats each planned cell as an attempt. `code_extension.ledger.build_ledger`
reads the authorized plan and the dispatch cohort's run manifest, execution
records, evaluator evidence, and operating records. It creates exactly one row
per planned cell, including a cell that never settled. `attempted` counts these
planned cells; `completed` counts cells that submitted a retained candidate;
`passed` counts candidates the external evaluator marked correct. The three
counts are always shown separately by scenario and arm.

A failed settled cell has one failure category. `classification.classify` maps
typed infrastructure, provider, and timeout causes mechanically. It also marks
incorrect candidates as invalid or incomplete versus valid but wrong using the
retained group verdicts. The six judgment categories require an operator
identity and the digest of the retained trace being reviewed. An operator
judgment cannot override a mechanical category. A passing candidate has no
failure category. A cell that never started has no patch or trace bytes; its
reference resolves to the run manifest that records its missing coordinate.
Partial patches and trajectories retained by Pier are linked when present.

The evaluator's per-group verdict remains the oracle. Agent self-assessment is
read from the retained submission and displayed alongside the independent
verdict. A missing evaluator verdict stays unavailable. Scope of diff is
measured from the committed fixture tree against the tree after applying the
retained patch, using `assay.code_metrics.snapshot_directory` and `compare`.
The locked TypeScript and node toolchains are prepared before measurement;
measurement itself installs and fetches nothing. The expected path set for
unnecessary-change counts is a declared task input, not inferred from the
patch. Duration, usage, tool calls, inspected files, retries, and self-report
come from retained execution and trajectory evidence.

`code_extension.publish.render` produces the committed
[`REPORT.md`](../experiments/code_extension/REPORT.md) from committed fixture
manifests and committed run evidence. At present, the fixture roster is
qualified but there is no committed extension run bundle, so observed attempt
counts are empty. A run bundle belongs under
`experiments/code_extension/evidence/runs/<run>/`: `run.json` names the
content-addressed plan and run-manifest refs, trace-bound operator judgments,
and the expected changed paths per subject; `objects/sha256/` contains those
records and their closure. The publisher reads each bundle, builds its ledger,
measures retained patches and trajectories, then regenerates the report. Run
`uv run python -m code_extension.publish --write` from `experiments` to update
the committed text. The report equality test catches stale text. The report
separates implementation success,
verification behavior, and operational failures. An unpriced local route has
coverage `unavailable` or `uncertain` and no amount, currency, or pricing
basis. Unknown coverage appears in its own column, and an unpriced arm is not
ranked as cheaper than a priced one. An index-use count is accompanied by its
run's declared `index_agent_readable` policy; that policy does not enforce
access to hidden paths.

The pinned statistical profile requires ten common subjects for inference.
Below that floor, the report is descriptive only and contains raw counts,
without significance tests or adjusted intervals. Scenario difficulty and
operational failures must be discussed separately from code-shape effects.
