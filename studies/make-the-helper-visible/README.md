# Coding models follow the helper they can see, not the codebase's consistency

I tested a simple question: when a coding model adds code, does it reuse an
existing shared helper, or does it copy the inline duplicates around it?

- **Synthetic files.** Weaker models started copying the mess from the first
  inline caller. Sol and Sonnet held out until the whole file bypassed the
  helper.
- **Real repositories.** I used slices of two of our own repositories. Inline
  copies in other files changed nothing for any of four models.
- **What moved reuse:** whether the target file imported the helper, and which
  model wrote the code.

[Supporting data](./supporting-data.md) covers the setup, per-subject results
and limits.

## Each subject differed only in how existing callers reached the helper

Every subject has two arms:

- **Clean arm:** the existing callers use the helper.
- **Inconsistent arm:** the same callers inline the helper's logic.

The helper, the task and the target file are identical in both arms. The task
asks for exactly what the helper does.

A structural evaluator labels each output *reused* or *duplicated* from the
code itself. Hidden tests check correctness separately. Each subject × arm cell
ran twice. I compared the arms per subject with an exact paired sign test.

## In small files, the mess spread only to weaker models

The synthetic set has twelve subjects. Each target file has ten callers of the
helper, and a growing number of them are written inline. The table shows cells
that reused the helper, out of 24.

| Inline callers | Sol | Sonnet | Gemini | Haiku 4.5 |
| --- | ---: | ---: | ---: | ---: |
| 0 of 10 | 24 | 23 | 21 | 15 |
| 1 of 10 | 24 | 23 | 20 | 10 |
| 5 of 10 | 20 | 21 | 15 | 11 |
| 10 of 10 | 2 | 14 | 0 | 2 |

- **Sol and Sonnet** held until all ten callers were inline.
- **Gemini** degraded gradually, and only on one-line cross-module helpers.
- **Haiku 4.5** drifted from the first inline caller.

Two further variants changed nothing: chaining five additions did not
snowball, and padding the repository to 90 KB had no effect.

## In real code, distant mess changed nothing

The real-code set has eleven subjects, taken from pinned snapshots of
[jig](https://github.com/RankOneLabs/jig) and
[scout](https://github.com/RankOneLabs/scout).

- **The task:** each asks for a new function in a nearly empty module. One
  existing helper already provides that behaviour, such as parsing tool-call
  arguments or a `Retry-After` header.
- **The inconsistent arm:** two or three existing callers in other files
  inline the helper.
- **Prompt size:** 135–156 KB.

The table shows cells that reused the helper, out of 22, as clean /
inconsistent.

| Target module | Haiku 4.5 | Gemini 3.1 Pro | GPT-6 Luna | GPT-6.1 Sol |
| --- | ---: | ---: | ---: | ---: |
| No helper import | 4 / 2 | 9 / 8 | 6 / 4 | — |
| Imports the helper | 8 / 8 | — | 16 / 18 | 18 / 18 |
| Plus an inline neighbour in the same file | 6 / 9 | 13 / 12 | 17 / 15 | 18 / 16 |

No run showed an arm difference, and no sign test came out below p = 0.5.

## Importing the helper did more than consistency

Without the import, every model mostly reimplemented the behaviour, in both
arms. With reuse that low even in clean code, the mess had nothing to change.

Adding the import, identical in both arms, raised clean-arm reuse:

- **Luna:** from 6 to 16 cells.
- **Haiku:** from 4 to 8 cells.

The inconsistent arm rose just as much.

## Mess in the same file spread on one subject

In the last variant, the target module also holds a neighbour function that
needs the same behaviour. In the clean arm the neighbour calls the helper. In
the inconsistent arm it inlines the logic.

On 10 of 11 subjects this changed at most one cell. The exception was
`usage-cost`:

- **Luna and Sol** reused `stamp_cost` in all 4 clean cells.
- **In all 4 inconsistent cells**, they copied the neighbour's inline
  `compute_cost` instead.

```python
# clean:        stamp_cost(usage, payload["model"])
# inconsistent: if cost is None: cost = compute_cost(payload["model"], ...)
```

Both versions pass the tests. The neighbour calls a legitimate shared
function, so copying it reads as local style rather than a shortcut.

Gemini and Haiku duplicated this subject in the clean arm too. They never
reused the helper here, so the mess had nothing to pull them away from.

## Models differed more than arms

These comparisons count reused cells per subject, with the helper imported.

| Comparison | Subjects where the first reused more | Subjects where it reused less | Sign test |
| --- | ---: | ---: | ---: |
| Sol vs Haiku 4.5 | 6 | 0 | p = 0.03 |
| Luna vs Haiku 4.5 | 5 | 0 | p = 0.06 |
| Luna vs Sol | ≤ 1 cell apart on every subject | | |

- **Haiku 4.5's repeat duplicates.** It duplicated the same four helpers every
  time, even with the import a few lines above.
- **Correctness.**
  - Luna and Sol were correct on all 11 subjects in every run.
  - Gemini was correct on 10 of 11.
  - Haiku was correct on 8 of 9 scored subjects, and 7 of 10 with the
    neighbour.
- **Cost.** Luna matched Sol's reuse at about a twentieth of the price: $0.12
  against $2.28 per run.

The model ordering matches the synthetic results. The experiment was designed
to compare arms, so treat these model comparisons as exploratory.

## What I would take from this

- **Make the helper visible to the model.** An import, a nearby caller or a
  mention in the prompt did more than cleaning up distant callers.
- **Model choice dominates.** It mattered more than how consistent the
  codebase was.
- **The real risk is local mess that looks like legitimate style.**
- **A standard duplication gate catches the costly duplicates.** In the
  synthetic set they were route views, about 3× the code and complexity of a
  reused route, and jscpd flags every one at its default settings.

Next steps:

- Run Gemini on the helper-import variant.
- Add more repeats on the same-file variant.
- Try an agentic version, where the model can search the repository before
  writing.
