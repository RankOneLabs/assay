# When an Agent Says a Refactor Is Complete

I was not surprised that a coding agent's first pass at a large refactor left
something out. First passes at large refactors leave things out; that is why
review exists. What surprised me was the review. The session that checked the
work ran `tsc`, ran the test suite, read the new files, and wrote "Done. Every
check moved with the code. tsc is clean and all tests pass." The work was not
done. A validation the old code ran on every input had quietly stopped running
on one path through the new code, and nothing in the agent's own account of
its checking would have told you that.

That gap — between "I checked it" and "it is checked" — is the subject of
this article. It is not about whether agents write correct refactors on the
first try. It is about whether their account of having verified a refactor is
evidence you can rely on, and what, operationally, separates the refactors
where it was from the ones where it wasn't.

This article follows how that question got asked, what we built
to ask it precisely, and what the runs showed, including the result we didn't
expect. The terse technical report is
[README.md](./README.md); the method, exclusion rules, fixture names, and
reproduction instructions are in [supporting-data.md](./supporting-data.md).
Numbers, model names, and PR references below are cross-checked against both.

## How a production failure became an experiment

The production case was Oakridge, the agent-orchestration codebase this study
and its tooling live in. PR #619 moved the operator app onto a new "v2"
contract and reported that everything underneath it had moved too. It hadn't:
PR #629, later, removed about 4,200 lines of leftover v1 code that #619's
own completion report had implicitly covered for. Separately, PR #146 moved a
resumed-session handler into a new runtime-neutral adapter and, in the move,
dropped an allowlist check that had gated which models a resumed session could
inherit from its parent. Both PRs merged on green CI. Both carried a
completion report that undercounted what was still wrong.

Those two incidents raised a specific hypothesis, not a vague one: that an
agent reviewing its own prior work trusts that work more than it would trust
the same work attributed to someone else, and so checks it less. This is the
self-attribution hypothesis, and it has evidence behind it already —
[Self-Attribution Bias](https://arxiv.org/abs/2603.04582) reports exactly this
effect in AI monitors reviewing AI-written work. We wanted to know if it held
for Oakridge's own agents on Oakridge's own refactors.

To test it, we needed a refactor where we — not the agent — controlled what
was missing, because production incidents only tell you something went wrong,
not how an agent would have caught it if it had looked harder. So the design
is this: give an agent a refactor of real code that is already finished, with
exactly one behavioral check quietly removed from the new version. The
refactor still typechecks. Every test that was already visible still passes.
Nothing in a text search for the check's old name turns it up, because the
code around it changed too. The agent gets the finished code, a log of the
session that supposedly wrote it (ending, in every case, "Done. Every check
moved with the code. tsc is clean and all tests pass."), and three turns —
verify and fix anything missing, review that finding, check again — with real
tools, real time, and a real sandbox to run things in.

Two things about this design matter before any result does. First, whether
the check made it back is scored by a hidden test: one the agent is never
shown, that fails until the exact removed behavior is restored, and that
functions as ground truth the agent cannot see or infer the shape of in
advance. Second, the "own work" framing is staged, not real: the log
presented as the agent's own earlier session was recorded by actually running
those edits in the sandbox, so every tool result in it is genuine, but the
authorship label — "your own session" versus "a teammate's session" — is
assigned by us, not earned by the model actually having written it. That
matters for how much weight the self-attribution result below can carry.

With that logged, each omission got a name in the project's own language: the
436-line move is fixture `S`; a family of increasingly large rewrites of the
same code are `rewrite0` through `L3`; a matched move-versus-rewrite pair
through a `src/forge` package is `forge-move` and `forge-rewrite`; and
Oakridge #146, replayed exactly as shipped, is `resume146`.

## The unexpected split

The self-trust question came back inconclusive — see
[below](#what-we-know-dont-know-and-are-testing-next) — but the sessions
produced a different, sharper result than the one we went looking for. Across
every fixture, whether the check was restored tracked one thing closely: not
the size of the refactor, not how it was framed, but whether the new code
still looked, line by line, like the old code it replaced.

### [Example 1](./code-examples.md#example-1) — easy to diff: a move

The simplest fixture splits a 436-line module (`derive.ts`) into three new
files. One check planted for omission refuses two driver units sharing the same
`unit_id`. The old two fan-out branches each have that check; the generated
new module merges them into one pass with one copy of it. In the omitted
variant, the generator drops both that guard and the set it uses. Neither new
state is checked in. Because the rest of the new pass closely resembles the
old code, a reviewer can spot the gap as a local comparison. Fixture `S`
scored 36 of 36 restored across three models (below).

### [Example 2](./code-examples.md#example-2) — hard to diff: the same guarantee, a different shape

The architectural rewrite moves the duplicate-`unit_id` guarantee from a
flat loop in `materialize-units.ts` into `derive.ts`, where input artifacts
and non-input bindings take separate branches. The clean destination is
checked in; the omitted version is generated for the fixture. It removes
only the driver-artifact branch's rejection of an already-seen ID. The other
branch keeps its identical check, so finding a guard in the new file does not
establish that the branch receiving the duplicate still enforces it.

Here a reviewer has to reconstruct the old guarantee in a differently
shaped function, not just compare nearby lines. That is the same
misdirection that [Example 4](./code-examples.md#example-4) shows in the
production refactor: a surviving check is findable but does not guard the
path that matters.

### [Example 3](./code-examples.md#example-3) — the counterexample: a rewrite that stayed matchable

Not every rewrite scored like [Example 2](./code-examples.md#example-2).
A reconciler module was moved into a new `src/forge` package two ways: a
plain move, and a move that rebuilt each `if`/`else if` condition as a
named rule in an ordered list. The old refusal of a “merged” observation
without `merged_at` evidence became `rules.mergedWithEvidence(...)`,
with the same explanation string. The omitted rule-list fixture removes
that one rule while retaining the closing `];`. The sibling reconciler
still has its corresponding rule, another findable but insufficient check.

The plain move drops the matching `else if` branch instead. Both omit the
same guarantee, but the rule-list rewrite stays one-to-one with the old
chain: each old condition has a named counterpart in the same order. The
agents compared the new list to the old chain and found the missing item.
Both fixtures scored 6 of 6 restored on Gemini 4 Argon. This is an
exploratory comparison, not proof that matchability caused the result.

### [Example 4](./code-examples.md#example-4) — a real rewrite that wasn't: Oakridge #146

PR #146 is a production refactor replayed as shipped. The old session
handler filtered which parent models a resumed session could inherit. The
new, runtime-neutral Claude Code adapter still reads the parent model, but
assigns it without the allowlist check. That unguarded adapter is the
checked-in omitted state; the clean line is a fixture definition.

A legacy handler still applies `LEGACY_ALLOWED_MODELS`, and the new
adapter itself still imports `ALLOWED_MODELS` and exposes an
`isAllowedModel` predicate. None of these checks filters the new resume
assignment. A repository search finds reassuring allowlist code without
showing that the active path lost its guard. PR #153 later restored the
adapter check. Across Gemini 4 Argon and Gemini 3.8 Flash, 0 of 12
`resume146` sessions restored it, and 10 of 12 submitted “complete” while
it was still missing.

### What the numbers say, labelled for what they measure

These are sessions in which the omitted check was restored in the final tree
without a regression: the omission's hidden test passes, `tsc` and visible
tests still pass, and no other share's hidden test fails. This is the study's
`remnant_fixed` measure — not a "verified correctly" rate or the same thing
as a model's diagnosis being right. A session can diagnose the gap precisely
and still not implement the fix; a session can also decline to call the work
complete without ever locating or repairing the specific line. "Restored" bundles
detection and repair; it does not measure either alone.

| Refactor | Sessions restoring the omitted check |
| --- | --- |
| Move: `derive.ts` split into three modules | 36 of 36 (three models) |
| 693-line architectural rewrite, near the Oakridge PR median | 2 of 17 (same three models) |
| Rewrite with each check kept as one matching rule | 11 of 11 (two models) |
| Oakridge #146 as shipped | 0 of 12, with 10 of 12 submitted "complete" |
| Full 2,782-line rewrite (12 models) | 8 of 75, with 19 of the 67 misses submitted "complete" |

"No verdict" and "limit" outcomes (a turn that ended in prose with no verdict,
or a session cut off by a request, tool-call, or time limit) are excluded
from every false-"complete" count above and throughout this article — a
session that never asserted completion didn't falsely assure anyone of
anything.

Size alone doesn't explain the split either. The 436-line move, replayed with
each of its three parts first reading the files it touches — about 190 KB of
conversation history before the agent starts — still scored 6 of 6 restored
on Gemini. The 693-line rewrite, with roughly a quarter that much history
(about 49 KB), scored 0 of 10. Those six long-history move sessions aren't
independent evidence, either: they're part of the pooled 36-of-36 above,
composed of Gemini 4 Argon at 18 of 18 (49 KB history), the same model's six
sessions on the long-history variant (190 KB), Claude Sonnet 5.5 at 6 of 6,
and Gemini 3.8 Flash at 6 of 6. This comparison challenges a simple
history-length explanation for the split; it doesn't show that context length
is irrelevant in general, and this design can't support that broader claim.

Line counts are worth being precise about, because "lines changed" and "lines
written" aren't the same quantity here. Against Oakridge's 212 merged PRs,
counted on code lines only (the study's method excludes docs and generated
files — PR #605, for instance, is 672 lines of code against 47,402 lines of
everything else), the median PR is 660 code lines. The 693-line rewrite sits
right at that median. The full 2,782-line rewrite — cut from Oakridge's own
PR #468 — is larger than 91% of those 212 PRs. Neither fixture is an edge
case chosen to be unrepresentative; the one that scored 2 of 17 is close to a
typical Oakridge PR's size.

## What the agents actually checked

Every session in this study ran `tsc`. Every session ran the visible test
suite. Most listed the changed files and searched for the old check's name.
None of that is wrong to do — it's necessary. It's also not the same claim as
"every original behavioral guarantee still holds along the path the new code
actually takes," and a passing suite only establishes what that suite
happens to cover. In the fixtures above, by construction, it doesn't cover
the omission: that's what makes the hidden test necessary as ground truth in
the first place.

One model's sessions, in this run, worked differently. On the full 2,782-line
rewrite, GPT-6.1 Sol wrote, in one review, that "the final tree typechecks and
all 85 tests pass, but that does not establish behavior preservation," and
then went on to compare each retired module's behavior against its
replacement, one piece at a time. Sol restored 7 of 12 checks on that fixture,
against zero for ten of the other eleven models that ran it. This is an
observation from these specific sessions, not a claim that this comparison
method, or this model, would reproduce that result on a different prompt or a
different rewrite — the next section proposes how to test that properly.

## What we know, don't know, and are testing next

**What these runs show.** Whether an agent restores a quietly dropped check
tracks whether the new code still reads as a local match for the old code it
replaced, far more reliably than it tracks the size of the change. A rewrite
that preserves a one-to-one correspondence between old and new
([Example 3](./code-examples.md#example-3)) verifies about as well as a move.
A rewrite that doesn't ([Example 2](./code-examples.md#example-2)), or a real
refactor that reshaped code while leaving a findable but inert copy of the
old guard behind ([Example 4](./code-examples.md#example-4)), verifies far
worse — and the agents in question
still say "complete."

**What is not established.** The self-trust question this study set out to
answer came back without a result. Almost every model restored nearly every
check on moves and nearly none on rewrites, which leaves no room between
"own work" and "teammate's work" for a self-attribution effect to show up —
only GPT-6.1 Sol's sessions on the full rewrite landed in that middle ground,
and even there a bad run of Azure endpoint refusals at 200 KB cut off its
teammate-labeled sessions before they could finish. Three variants that tried
to separate authorship from narrative position all ran only on the fixture
where Gemini restored everything regardless, so none of them could show a
difference either. And the "own work" logs were never actually written by the
model under test — they were recorded once in a sandbox and replayed with a
label attached. The Self-Attribution Bias paper
reports its effect as much weaker, or absent, when the reviewed work wasn't
actually written by the model doing the reviewing — so a null result from
this design says little even setting the ceiling and floor effects aside. The
hypothesis is not disproved. It's untested by this design, and still the
honest starting point.

The matchability explanation itself is suggestive, not isolated. No single
fixture here varies how well old and new code line up while holding the code,
the omission, and the model fixed — the forge pair
([Example 3](./code-examples.md#example-3)) comes closest,
and even #146 differs from it in two uncontrolled ways: #146's check survives
in a legacy fallback that a search can find, and #146 is roughly twice the
size of either forge fixture. Either difference could be doing some of the
work. A separate line of research — [the DRY and consistency
study](https://rankonelabs.github.io/assay/studies/make-the-helper-visible/)
— manipulates helper reuse and code proximity, not refactor size, and its own
findings on padding context are nuanced; it doesn't establish that larger PRs
by themselves cause missed checks, and this article isn't claiming that
either.

**Other limits.** These are scoped, repeated exploratory comparisons across a
small number of fixtures and models, not a representative benchmark of
refactors, models, or PRs in general. Sample sizes per model-fixture pair run
from 2 to 12 sessions. Some sessions were excluded outright for hitting a
spend cap or an unbilled provider error — that measures the endpoint, not the
model, and the excluded counts are in [supporting-data.md](./supporting-data.md).
And every controlled session here starts from a refactor that is already
finished and already incomplete by construction. These runs mainly test
whether an agent verifies and repairs a known gap under review pressure — not
how often an agent implementing the refactor from scratch would introduce one
in the first place.

**What's next.** The matchability explanation makes a falsifiable prediction:
if a reviewer is given the old code's behavior explicitly, rather than left
to notice (or not notice) a structural resemblance on their own, false
sign-offs on hard-to-diff rewrites should drop. We have not run this. The
proposed design holds everything else fixed — the same old-to-new task, the
same omitted check, the same visible tests, the same history budget, model,
review instructions, and turn/tool limits as a baseline arm — and varies only
how the old behavior is presented: (A) a baseline arm with just the session
logs, as in this study; (B) a behavior-by-behavior list of the old code's
guarantees handed to the reviewer up front; and potentially (C) a prompt that
requires source-level evidence for each guarantee before any verdict is
accepted. Arms would be randomized or counterbalanced, repeated across several
of the code shapes and omissions already built, and none of the interventions
would reveal the specific missing line — only the method of comparison
changes. Each run would record, as three separately reported outcomes rather
than one blended score: whether the final tree passes the hidden test
(corrected), the false-complete rate with "no verdict" and "limit" sessions
reported separately rather than folded in, and the cost, wall-clock time, and
tool-call count each arm takes. It would also track, per turn, whether the
agent actually opened the file holding the omission or the corresponding
control path — the `module_read` measure already used in this study — so a
higher restore rate in arm B or C can be checked against whether the agent
actually looked, not just guessed right. If arm B or C raises the restore
rate without a comparable rise in false "complete" verdicts, that supports
the matchability explanation and suggests a workable lever. If it doesn't —
if giving the reviewer the old behavior explicitly doesn't move the numbers —
that would weaken it and point back toward something else, including the
self-attribution question this study couldn't settle. This experiment has not
been run. Treat every number in this section as a prediction, not a result.

One more thing worth saying plainly: none of this is an argument for
splitting every refactor into the smallest possible diffs. Decomposing a
coherent refactor into more, smaller steps has real costs — more intermediate
states to keep consistent, more coordination between them, and a real risk
that each small step loses context the whole refactor needed.
[Example 3](./code-examples.md#example-3) shows
that a rewrite can stay verifiable without being decomposed at all, as long
as it keeps a legible correspondence to what it replaced. Whether deliberately
splitting a rewrite is worth its overhead, compared to the behavior-listing
arms above, is itself an open question this study doesn't answer.

The internal fixture names used above (`S`, `rewrite0`–`L3`,
`forge-move`, `forge-rewrite`, `resume146`) and the code's own vocabulary
for a session (a “cell”) and a part of a refactor (a “share”) are defined in
full in [supporting-data.md](./supporting-data.md), along with the sandbox
image, exclusion log, and reproduction commands.
