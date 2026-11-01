# Code extension study report

Generated from committed fixture manifests and retained run evidence. The fixture roster is qualified; no extension run bundle is committed when the attempt counts below are empty.

Unavailable means no retained measurement. Invalid means a dispatched attempt with an infrastructure failure. Unevaluable means a dispatched attempt without an independent grade. Primary success means normal completion, an independent grade, all checks passing, and a clean edit scope. No candidate counts attempts without a retained patch.

## Implementation success

Common subjects with an attempt in every arm of a multi-arm run: 0. Descriptive only; no inferential statistics are calculated.

| Scope | Attempted | Completed | Passed |
|---|---|---|---|
| All attempts | 0 | 0 | 0 |

Per-scenario counts:

| Scenario | Attempted | Completed | Passed |
|---|---|---|---|
| oakridge-dbos-context-defaults | 0 | 0 | 0 |
| oakridge-dbos-cross-module-event | 0 | 0 | 0 |
| oakridge-dbos-dispatch-handler | 0 | 0 | 0 |
| oakridge-dbos-pointer-root | 0 | 0 | 0 |
| oakridge-dbos-stage-pass-through | 0 | 0 | 0 |

Per-arm counts:

| Arm | Attempted | Completed | Passed |
|---|---|---|---|
| baseline | 0 | 0 | 0 |
| central | 0 | 0 | 0 |
| cross_module | 0 | 0 | 0 |
| modular | 0 | 0 | 0 |
| plugin | 0 | 0 | 0 |

Scenario/arm cells, including cells with no completed attempt:

| Scenario | Arm | Attempted | Completed | Passed |
|---|---|---|---|---|
| oakridge-dbos-context-defaults | baseline | 0 | 0 | 0 |
| oakridge-dbos-cross-module-event | baseline | 0 | 0 | 0 |
| oakridge-dbos-dispatch-handler | baseline | 0 | 0 | 0 |
| oakridge-dbos-pointer-root | baseline | 0 | 0 | 0 |
| oakridge-dbos-stage-pass-through | central | 0 | 0 | 0 |
| oakridge-dbos-stage-pass-through | cross_module | 0 | 0 | 0 |
| oakridge-dbos-stage-pass-through | modular | 0 | 0 | 0 |
| oakridge-dbos-stage-pass-through | plugin | 0 | 0 | 0 |

## Verification behavior

Agent self-assessment is shown only beside the independent evaluator verdict. An unavailable verdict remains unavailable.

| Attempt | Agent assessment | External verdict | Agreement |
|---|---|---|---|

Declared `index_agent_readable` is operator policy, not an enforced access boundary. Index use is interpreted beside that declared policy:

| Arm | index_agent_readable | Index queries |
|---|---|---|
| baseline | undeclared | 0 |
| central | undeclared | 0 |
| cross_module | undeclared | 0 |
| modular | undeclared | 0 |
| plugin | undeclared | 0 |

## Operational failures

| Category | Attempts |
|---|---|

Cost coverage is reported separately from implementation effects. Unpriced local usage is never treated as zero cost or ranked against priced usage.

| Arm | Priced | Unavailable | Uncertain | Observed cost |
|---|---|---|---|---|
| baseline | 0 | 0 | 0 | unpriced |
| central | 0 | 0 | 0 | unpriced |
| cross_module | 0 | 0 | 0 | unpriced |
| modular | 0 | 0 | 0 | unpriced |
| plugin | 0 | 0 | 0 | unpriced |

## Secondary measures

Scope of diff and unnecessary changed paths come from offline `assay code-metrics` comparison of the committed fixture tree with the patched tree. The expected path set is declared per task; an unmeasured path count stays unavailable.

| Attempt | Changed paths | Unnecessary paths | Duration s | Prompt tokens | Completion tokens | Tool calls | Files inspected | Retries |
|---|---|---|---|---|---|---|---|---|

## Scenario outcomes

This table counts primary attempts only, including invalid and unevaluable primary attempts. Other tables count all retained attempts. In the CSV and JSON ledgers, `retry_of` is `none` for a primary attempt and names the original attempt for a retry.

Intervals use the Wilson score method at alpha 0.05. They describe execution variability on a fixed task, rather than sampling error over tasks. The fixture roster shown here lists 5 qualified scenarios; the planned pilot has fifteen attempts, five repeats on each of three fixed tasks. Only retained planned coordinates count as attempts. The repeats are not fifteen independently sampled tasks.

| Scenario | Planned | Missing | No candidate | Operational yield | Primary task success | Conditional correctness | Invalid | Unevaluable |
|---|---|---|---|---|---|---|---|---|
| oakridge-dbos-context-defaults | 0 | 0 | 0 | 0/0 (unavailable; 95% interval unavailable) | 0/0 (unavailable; 95% interval unavailable) | 0/0 (unavailable; 95% interval unavailable) | 0 | 0 |
| oakridge-dbos-cross-module-event | 0 | 0 | 0 | 0/0 (unavailable; 95% interval unavailable) | 0/0 (unavailable; 95% interval unavailable) | 0/0 (unavailable; 95% interval unavailable) | 0 | 0 |
| oakridge-dbos-dispatch-handler | 0 | 0 | 0 | 0/0 (unavailable; 95% interval unavailable) | 0/0 (unavailable; 95% interval unavailable) | 0/0 (unavailable; 95% interval unavailable) | 0 | 0 |
| oakridge-dbos-pointer-root | 0 | 0 | 0 | 0/0 (unavailable; 95% interval unavailable) | 0/0 (unavailable; 95% interval unavailable) | 0/0 (unavailable; 95% interval unavailable) | 0 | 0 |
| oakridge-dbos-stage-pass-through | 0 | 0 | 0 | 0/0 (unavailable; 95% interval unavailable) | 0/0 (unavailable; 95% interval unavailable) | 0/0 (unavailable; 95% interval unavailable) | 0 | 0 |

## Terminal causes and measurement coverage

| Scenario | Terminal causes | Duration measured | Tool use measured | Tokens measured | Cost priced |
|---|---|---|---|---|---|
| oakridge-dbos-context-defaults | unavailable | 0/0 | 0/0 | 0/0 | 0/0 |
| oakridge-dbos-cross-module-event | unavailable | 0/0 | 0/0 | 0/0 | 0/0 |
| oakridge-dbos-dispatch-handler | unavailable | 0/0 | 0/0 | 0/0 | 0/0 |
| oakridge-dbos-pointer-root | unavailable | 0/0 | 0/0 | 0/0 | 0/0 |
| oakridge-dbos-stage-pass-through | unavailable | 0/0 | 0/0 | 0/0 | 0/0 |

## Interpretation

These scenario results do not isolate a code-shape effect. The fixture roster alone supplies no implementation effect.
