# Verification pilot decisions

The fixed inputs live in `inputs.py`. G3 uses four type renames:
`StageInstanceId` → `StageRunId`, `WorkflowRunId` →
`WorkflowExecutionId`, `RunUnitId` → `ExecutionUnitId`, and
`WorkOrderId` → `TaskOrderId`. The pilot system prompt, three turn texts, and
submission shapes are named and typed there. The pinned Pier tool digest stays
unchanged because the six-tool surface and its T1 versus review submission
fields have not changed.

The raw Oakridge repository slice lives in `raw/repo/`. Its README records
provenance and makes clear that it is inert input data. `fixtures.py` reads the
slice, matches symbols at whole-word boundaries, derives use sites, and assigns
three owners in deterministic sorted round-robin order. At the pinned slice the
file counts are 20, 18, 10, and 8 respectively; the new spellings occur in no
file. Even the eight-file rename gives every owner at least two files.

G6 plants `CHANGELOG.md` and `docs/migration.md` as historical decoys per
subject. They are absent from the raw slice. For each rename, the derived
population has one planted remnant in each of the three owner shares and one
clean control, yielding 16 base subjects. The 12 planted subjects each receive
native and quoted T1 presentation, yielding 24 sessions. The clean controls
remain in the declared population and are excluded from the active session
shard. `study.py` obtains the subjects and active coordinates from these fixture
records, with one worker execution per session.

G15 declares one evaluator, `pilot_judge`, per active session. The prior
scripted grid of separate per-turn and per-owner evaluator declarations is
retired. The scripted run verifies the shape and sealed trace path; it is not
a measured model result. The published study has pending results only, so
replacing the old design does not erase a measured finding.

The existing pilot tool digest, route bounds, and worker loop remain pinned.
Any later loop or measurement changes belong to later cohorts. The
qualification smoke must be reviewed before live results are interpreted.

D16: the smoke and full Tier 1 shards use the same authorized 96-cell,
345,600-second, one-worker ceiling. The report engine includes that ceiling
in its 0.3.0 compatibility fingerprint and refuses to pool shards with
different fingerprints. The 2 × 4 × 2 × 1 smoke geometry and fixed statistical
and ceiling rules are pre-registered in `SMOKE.md` before any live cell runs.
`ReportConfig`, `StatisticalProfile`, and the shared report engine are unchanged.

D17 (2026-10-18): the paid route is chosen by screening. The route pinned
on 2026-09-16, `anthropic/claude-3-haiku` on Amazon Bedrock, has had no
OpenRouter endpoints since 2026-09-30, so no paid cell ever ran on it. It was
an infrastructure choice, the cheapest guarded route, not a study decision.
The local smoke showed that tool competence, not verification behavior,
limited a small model. The paid arm is therefore chosen by evidence rather
than by name.

Six candidates from six labs each get one pinned zero-data-retention endpoint
with tool calling. Each endpoint's listed price on 2026-10-18 is its
`max_price`, and a one-request identity probe the same day confirmed the
returned `model` and `provider`:

| `--paid-route` | Model | Endpoint | USD per million (prompt / completion) |
| --- | --- | --- | --- |
| `sonnet-5.5` | `anthropic/claude-sonnet-5.5` | `amazon-bedrock` | 2.00 / 10.00 |
| `gpt-6.1-sol` | `openai/gpt-6.1-sol` | `azure/us` | 2.20 / 11.00 |
| `gemini-4-argon` | `google/gemini-4-argon` | `google-vertex/global` | 2.00 / 10.00 |
| `qwen3.8` | `qwen/qwen3.8-2.4t-a95b` | `siliconflow/fp8` | 2.00 / 6.00 |
| `deepseek-v4-pro` | `deepseek/deepseek-v4-pro` | `siliconflow/fp8` | 1.502 / 3.135 |
| `kimi-k2.7-code` | `moonshotai/kimi-k2.7-code` | `moonshotai/int4` | 0.95 / 4.00 |

Open-weight endpoints are pinned at fp8, or at Kimi's native int4 release,
never a cheaper fp4 copy. Venice remains excluded. Each candidate runs the
registered eight-cell smoke under its own $2.49 cap. The screen's total
authorization is $15, which includes the $0.004 probe. A candidate becomes a
route only if all five smoke counts are zero. Route identity is in the
runtime fingerprint, so each qualified route keeps its own report. Choosing
among qualified routes for the full shard, and that shard's cap, is a
separate decision.

D17 clarification, recorded before any screening cell ran: the smoke's
tool-error count covers harness failures only. Those are failures of the tool
machinery, such as a tool timeout, a sandbox or capture failure, or an
invalid output encoding. A non-zero exit caused by the model's own call, such
as a `replace_in_file` whose text is absent or `git` outside a repository,
returns its error text as the tool result. The model can then recover, and
that exit does not fail a route. Each route still reports model-caused tool
errors and tool-call-limit stops beside the five counts. Every call counts
toward the 15-per-turn and 40-per-cell limits.

D18 (2026-10-18): read-only shell commands count as file inspections. The
first screening route, Sonnet 5.5, inspected the native-arm repository
entirely through `run_command` (`git status; grep -rn WorkOrderId .`). The
registered measures count only `read_file` and `search_files`, so all four
native sessions scored an ownership gap of 1.0 and no remnant inspection,
although the transcripts show a repository-wide search of the old symbol.
Any capable model that prefers the shell would bias H1 and H4 the same way.

`shell_inspection.py` turns each recognized segment of a successful
`run_command` into the equivalent virtual call, placed where that command
ran:
- `grep`, `egrep`, `fgrep`, `rg` and `git grep` become searches.
- `cat`, `head`, `tail`, `nl`, `sed -n` and `awk` with explicit operands
  become reads.

The parse is quote-aware and fails closed. These are not inspections:
- a pipe-only `grep`;
- a glob or variable path;
- `sed -i`, or a redirection target;
- a path outside `/workspace`;
- anything that does not tokenize.

The command must have exited 0, or 1 for a lone search segment. Search
queries obey the existing rule: the old symbol must appear as a whole word,
so a case-insensitive regex such as `workflow_?run_?id` does not count. Line
ranges are unchanged, so a shell read does not satisfy the line-level
`remnant_read`.

Measures are a pure function of a trajectory, so
`python -m verification_pilot.run remeasure --archive raw/runs/<run_id>`
re-derives archived measures without re-running. Re-scoring changes only
Sonnet's four native sessions: first wide search goes from absent to true,
ownership gap from 1.0 to 0.0, and remnant inspection from false to true.
The local Qwen run is unchanged. The bridge also now records the text of a
reply that ends a cell without a tool call, as `reply_without_tool_call`, so
the manual read can see it.
