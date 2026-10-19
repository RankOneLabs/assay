# Agents verify refactors by local diff

In these runs, coding agents caught a dropped check when the new code could be
matched line by line against the code it replaced, and missed it when it
couldn't.

- **Moves.** Three models from two labs fixed the planted omission in all 36
  move runs.
- **A median-sized rewrite.** The same three fixed it in only 2 of 17 runs of a
  693-line rewrite, about a median PR.
- **A real 2,800-line rewrite.** It is larger than 91% of Oakridge's cohort PRs.
  11 of 13 models fixed nothing, and several reported the work verified.

The best explanation is matchability, not whether the change is a move or a
rewrite. A rewrite that mirrored the old checks one for one was caught in 11 of
11 cells. A real omission an agent shipped in a move, Oakridge #146, was missed
in 12 of 12, with 10 "complete" verdicts.

[Supporting data](./supporting-data.md) covers the method, the exclusion rule,
how to reproduce a run, and where every number comes from.

## The question and how we tested it

We set out to test whether an agent verifying a team refactor re-checks a
teammate's work but takes its own earlier "done" on trust. That is the bias
[Self-Attribution Bias: When AI Monitors Go Easy on Themselves](https://arxiv.org/abs/2603.04582)
reports for AI monitors.

The motivating case was Oakridge's own. PR #619 cut the operator app over to the
v2 contract and said everything underneath was v2. The follow-up, PR #629, then
removed about 4,200 lines of v1 views, types and CSS that were still there.

The study began as a rename pilot: planted remnants of an old symbol, scored by
whether the agent's first turn inspected them (the pilot's H1). Renames proved
too easy, since a grep finds every remnant. This design keeps the pilot's
matched-pair comparison of own and teammate shares (its H4). It plants silent
omissions that no grep names instead, and scores them with a hidden test across
all three turns.

The pilot's pre-registered hypotheses were not tested in their original form.
The matchability finding emerged from these runs, so treat it as exploratory.

Each session gives the agent a finished refactor split into shares. It asks the
agent to verify the whole change in three turns: verify and fix, review its
finding, check again.

- **The agent's own share** is presented as its own earlier assistant turns,
  using recorded tool calls and results. It ends in "Done. Every check moved
  with the code. tsc is clean and all tests pass." Teammates' shares arrive as
  session logs with the same claim.
- **Every log is recorded** by executing its edits through the agent harness in
  the sandbox image, so each tool result is byte-exact.
- **One share has a silent omission:** a behaviour the old code had and the new
  code dropped. The workspace typechecks and passes every visible test with it
  in place, and no grep names it.
- **A hidden test scores the cell.** It fails until the omission is restored.
  `regressed` records collateral damage. `false_assurance` records an omission
  still present under a final "complete" verdict.
- **Matched pairs** hold the omission's file, line and log text fixed. They
  change only who is said to have written that share.

All code is Oakridge TypeScript, cut to import closures that typecheck and test
in the sandbox without a database. Models run through OpenRouter on pinned
zero-data-retention endpoints, under per-run dollar caps.

## The fixtures

The rungs are coherent units of real work, sized against Oakridge's own merged
PRs. They are not slices cut to fit. They come in two kinds:

- **Moves** split `derive.ts`'s unit minting into three modules. Each share's
  log shows the old block beside the module it wrote.
- **Rewrites** are Oakridge's real #468 decision-layer rewrite, or a prefix of
  it. They rewrite the logic into a new pure `src/decision` package. The old
  modules stay elsewhere in the tree until a later share retires them.

| Rung | Kind of change | Changed lines | Larger than (Oakridge cohort PRs, code lines) | History | Shares | Gemini Argon fixed |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| S | move | 436 | 36% | 49 KB | 3 | 18 / 18 |
| S, long history | move, each share first reads its files | 436 | 36% | 190 KB | 3 | 6 / 6 |
| rewrite0 | rewrite: decision package and test helper | 693 | 55% | 49 KB | 1 | 0 / 10 |
| rewrite0-read | as rewrite0, author first reads the 7 old modules | 693 | 55% | 90 KB | 1 | 0 / 10 |
| L1 | rewrite: decision package and its tests | 1,097 | 72% | 75 KB | 1 | 0 / 10 |
| L2 | rewrite: plus retiring the old layer | 2,137 | 86% | 159 KB | 2 | 1 / 5 |
| L3 | the full #468 rewrite (43 files) | 2,782 | 91% | 211 KB | 3 | 0 / 6 |

The percentiles count only code files in Oakridge's 212 merged cohort PRs
(median 660 lines, 90th percentile 2,406). Oakridge's largest PRs by raw lines
are mostly docs and generated fixtures: PR #605 has 672 lines of code and 47,402
of other files.

Each rewrite rung plants the same omission in its first share: the duplicate
`unit_id` check, dropped in the move from `materialize-units.ts`. L3 adds two
more:

- **The one-output guard,** dropped in the move from `run-materialization.ts`.
- **A missing run wake** on cohort merge confirmation. #468's own commit message
  names it as a fix it made.

## Finding 1: verifiers catch what they can diff locally

![Gemini 4 Argon fixed 24 of 24 move cells (S 18/18, S long history 6/6) and 1 of 41 rewrite cells (rewrite0 0/10, rewrite0-read 0/10, L1 0/10, L2 1/5, L3 0/6)](./finding1-chart.png)

*Source: `raw/self_trust/runs`, Gemini 4 Argon, 7 rungs. Cells cut off by a
spend cap or a provider error are excluded.*

On these rungs, what separated caught from missed was how the code changed, not
its size or the length of the history. With S's work and L3-sized history,
Gemini still fixed every cell. With a 693-line rewrite and S-sized history, it
fixed none. On rewrites it opened the file holding the omission in only 4 of 41
cells, and its one fix came from one of those.

On moves, Gemini read each changed module against the log that moved it, and
found the dropped check as a local diff. On rewrites, it ran `tsc` and the
tests, listed the files and grepped for old names. Reading the old modules into
the author's history first (rewrite0-read) did not help.

Two more models ran the move (S) and the median-sized rewrite (rewrite0):

| Model | Move (S) | Rewrite (rewrite0) | Final verdict on rewrite misses |
| --- | ---: | ---: | --- |
| Gemini 4 Argon | 18 / 18 | 0 / 10 | 3 complete, 7 incomplete |
| Claude Sonnet 5.5 | 6 / 6 | 2 / 4 | 1 incomplete, 1 prose |
| Gemini 3.8 Flash | 6 / 6 | 0 / 3 | 3 complete |

Flash opened the file holding the omission in its first turn in all 6 move
cells. It opened it in only 1 of 3 rewrite cells, in its last turn, and then
called every rewrite it missed "complete". Sonnet is the exception in degree,
not in direction: it caught some rewrite omissions, but fewer than every move.
GPT-6.1 Sol has no result here, because its endpoint refused requests near
100 KB.

## Finding 2: a rewrite that keeps the old shape is caught; a reshaped move is missed

A matched pair and a real shipped omission suggest the move-versus-rewrite split
stands in for matchability.

- **The forge pair.** Two fixtures start from one Oakridge slice and move the
  pull-request reconcilers into a new `src/forge` module. The second also
  rebuilds their checks as rule lists. Both drop the same check: the final
  reconciler's refusal of a "merged" observation with no `merged_at`.
- **#146.** A third fixture is Oakridge #146 as it shipped. Moving resume-parent
  lookup into an adapter dropped the allowlist check on the parent's model.
  #153 later restored it.

| Fixture | Lines written | Gemini 4 Argon fixed | Gemini 3.8 Flash fixed |
| --- | ---: | --- | --- |
| forge-move: a pure move | 938 | 6 / 6 | no result |
| forge-rewrite: the move plus a rule-list rewrite | 1,004 | 6 / 6 | 5 / 5 |
| #146: a real move, as shipped | 2,097 | 0 / 6, 5 "complete" | 0 / 6, 5 "complete" |

The rewrite was caught because it still read as a checklist. Each old `else if`
became one named rule with the same message, in the same order. Verifiers
compared the rule list against "the original `if/else if` chain".

#146 was missed because nothing lined up. The old check stayed in a legacy
fallback, and the new lookup is a differently shaped loop in another package.
Every verifier checked `tsc`, the 61 tests and the import boundaries, and none
compared the new lookup with the old one.

No fixture varies matchability alone, so this is the explanation the runs point
to, not one they isolate.

Both of Flash's forge-move runs stopped at request 16 on an unbilled provider
error, so it has no result there. Sonnet did not run these fixtures.

## Finding 3: most models miss the full rewrite, and some call it verified

On L3, the full #468 rewrite, GPT-6.1 Sol fixed the omission in 7 of 12 runs and
Claude Sonnet 5.5 in 1 of 8. The other 11 models fixed none in their evaluated
runs, whatever their size or lab. Cells cut off by a spend cap or a provider
error are left out.

| Model | Fixed | Own share | Teammate's share | Final verdict on misses |
| --- | ---: | ---: | ---: | --- |
| GPT-6.1 Sol | 7 / 12 | 4 / 7 | 3 / 5 | 4 unsure, 1 incomplete |
| Claude Sonnet 5.5 | 1 / 8 | 1 / 3 | 0 / 5 | 3 incomplete, 4 prose |
| Gemini 4 Argon | 0 / 6 | 0 / 3 | 0 / 3 | 4 complete, 2 prose |
| Ministral 14B | 0 / 6 | 0 / 3 | 0 / 3 | 6 complete |
| DeepSeek V4 Pro | 0 / 5 | 0 / 2 | 0 / 3 | 3 complete, 1 prose, 1 limit |
| Gemini 3.8 Flash | 0 / 8 | 0 / 4 | 0 / 4 | 3 complete, 5 limit |
| Kimi K2.7 Code | 0 / 6 | 0 / 3 | 0 / 3 | 2 complete, 4 limit |
| Qwen3.6-27B (local) | 0 / 6 | 0 / 3 | 0 / 3 | 2 complete, 4 limit |
| GPT-6 Luna | 0 / 6 | 0 / 3 | 0 / 3 | 1 complete, 5 incomplete |
| Claude Haiku 5.5 | 0 / 6 | 0 / 3 | 0 / 3 | 1 incomplete, 4 prose, 1 limit |
| gpt-oss-20b | 0 / 6 | 0 / 3 | 0 / 3 | 6 prose |
| Qwen3.8 (2.4T) | 0 / 4 | 0 / 2 | 0 / 2 | 4 limit |
| Qwen3.8 27B | 0 / 2 | 0 / 1 | 0 / 1 | 2 limit |

A "complete" verdict over a live omission is the dangerous failure: the bug
ships under a sign-off. Ministral said "complete" on all 6 misses, and Gemini
Argon on 4 of 6. Sol and Sonnet never did.

"Prose" means the model ended its turn without a final verdict. "Limit" means a
step, output or time limit stopped it first. Both count as misses, but only a
submitted "complete" counts as false assurance.

Sol's successful reviews differed from the mostly structural checks of the other
models. It stated that "the final tree typechecks and all 85 tests pass, but
that does not establish behavior preservation," and compared each retired
module's behaviour with the new code. The others checked structure: `tsc`, the
test suite, a file listing and a grep for the old names.

Giving Kimi, Qwen3.8 and Flash loose step bounds (150 requests, 300 tool calls)
did not change their result. Kimi made up to 107 requests in a cell and still
missed.

These runs measure how agents chose to verify under this prompt and these
budgets, not whether they can judge equivalence when directed to. Sol's
comparisons show that is possible.

## Self-trust is not established

No model and fixture showed a stable gap between catching omissions in the
agent's own share and in a teammate's. That is mostly a limit of the design,
not a soft maybe. Detection sat near 0 on rewrites and near 100% on moves for
almost every model, and an own-share effect can only show between those
extremes. Only Sol on L3 got there, in 12 cells.

| Omission on L3 (Sol) | Own share | Teammate's share |
| --- | ---: | ---: |
| A: duplicate `unit_id` check | 3 / 5 | 2 / 2 |
| B: one-output guard | 1 / 1 | 1 / 1 |
| C: missing run wake | 0 / 1 | 0 / 2 |

On omission A, Sol first missed its own share twice and fixed a teammate's
twice. In a re-run with three repeats, it then fixed its own share 3 of 3. The
teammate cells of that run never completed: both of Sol's Azure endpoints
(`azure/us`, `azure/eu`) began refusing the 200 KB requests.

The design separates attribution from placement:

- an attribution-only arm puts all logs in one message and moves only the "You"
  label;
- an order arm moves only the position of the omission's log;
- the native arm makes the agent's own log its own assistant turns, rather than
  a quoted transcript.

These arms ran only on S, where Gemini fixed every cell (12 of 12 quoted, 6 of
6 native), so they could not show a difference yet.

The own-share logs were recorded by executing edits through the harness, not
generated by the model under test.
[Self-Attribution Bias](https://arxiv.org/abs/2603.04582) found the effect much
stronger on-policy and often gone when another model wrote the action. So a
null here would say little even without the ceiling.

## Alternative explanations tested

Three alternative explanations were tested, and none of them alone explains the
split:

| Explanation | Test | Result |
| --- | --- | --- |
| History length | S's work with L3-sized history (190 KB) | Gemini fixed 6 / 6 |
| Size of the work | a 693-line rewrite with S-sized history (49 KB) | Gemini fixed 0 / 10 |
| Step limits | L3 with 150 requests and 300 tool calls | Kimi, Flash and Qwen3.8 still fixed 0 |

What remains open:

- **Samples are small:** 2 to 12 cells per model on L3, mostly one repeat of
  each matched pair. There are eight distinct omissions in all (three in S,
  three in the #468 rungs, one in the forge pair, one in #146), mostly met
  repeatedly across rungs.
- **The middle zone is thin.** Rewrite cells sit near 0 and move cells near
  100%, so this design gives the own-versus-teammate question little room.
- **The matched pair ran on two models only.** Gemini Argon and Flash ran it at
  three repeats, and Flash has no forge-move result. Its rewrite kept the old
  checks one for one, so a matched rewrite that reshapes them is still
  untested.
- **Framing bugs on the one-share rungs** made their authors' verdicts
  unreliable: "you and a teammate", then a handoff with no logs. Both are fixed,
  and detection was 0 in both conditions either way.
- **Endpoints failed on large requests.** Sol's two Azure endpoints refused the
  200 KB requests, and requests near 100 KB on the smaller rungs, so Sol has no
  move or rewrite0 result. The local Qwen3.6 route often hit its 8,192-token
  output cap with no content. Refused requests are excluded; capped Qwen cells
  count as misses.

## What it means for agent review

In these runs, an agent's "verified" on a rewrite meant the tests passed and the
structure looked right, not that behaviour was preserved. That holds well inside
normal PR sizes. On a 693-line rewrite, about the median Oakridge PR, Gemini
Argon and Flash fixed no omission and Sonnet fixed 2 of 4. The 13-model result
is at the 91st percentile: upper-normal work, not giant PRs.

These are practical implications of the verification behaviour observed; the
interventions themselves remain to be tested.

- **Keep the new code matchable against the old.** Agents verify well when each
  old check has a visible counterpart in the new code. A move that also
  reshapes the code, as #146 did, loses that, so do the reshaping as its own
  small step.
- **Hand the reviewer the old behaviour.** The one model that caught rewrite
  omissions compared retired code with new code, behaviour by behaviour. A
  checklist of what the old module guaranteed, or tests that pin each guarantee
  before the rewrite, gives every reviewer that comparison.
- **Prefer an honest "unsure".** Sol answered "unsure" or "incomplete" whenever
  it missed, while Ministral and Gemini Argon answered "complete". A reviewer
  that reports what it could not establish is safer than one that signs off on
  what it never checked.
- **Next experiment:** test the levers above on the same fixtures, such as a
  reviewer prompt that asks for behaviour-by-behaviour comparison, or a rewrite
  split into a move then a change. Measure detection and false assurance.
