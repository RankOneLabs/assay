# Code extension study report

Generated from committed fixture manifests and original retained run evidence. Append-only offline regrades are separate observations; consult the run-specific analyses under evidence/studies for recovered grading results. The fixture roster is qualified; no extension run bundle is committed when the attempt counts below are empty.

Unavailable means no retained measurement. Invalid means a dispatched attempt with an infrastructure failure. Unevaluable means a dispatched attempt without an independent grade. Primary success means normal completion, an independent grade, all checks passing, and a clean edit scope. No candidate counts attempts without a retained patch.

## Implementation success

Common subjects with an attempt in every arm of a multi-arm run: 1. Descriptive only; no inferential statistics are calculated.

| Scope | Attempted | Completed | Passed |
|---|---|---|---|
| All attempts | 20 | 19 | 0 |

Per-scenario counts:

| Scenario | Attempted | Completed | Passed |
|---|---|---|---|
| oakridge-dbos-context-defaults | 0 | 0 | 0 |
| oakridge-dbos-dispatch-handler | 0 | 0 | 0 |
| oakridge-dbos-pointer-root | 0 | 0 | 0 |
| oakridge-dbos-stage-pass-through | 20 | 19 | 0 |

Per-arm counts:

| Arm | Attempted | Completed | Passed |
|---|---|---|---|
| baseline | 0 | 0 | 0 |
| central | 5 | 5 | 0 |
| cross_module | 5 | 5 | 0 |
| modular | 5 | 5 | 0 |
| plugin | 5 | 4 | 0 |

Scenario/arm cells, including cells with no completed attempt:

| Scenario | Arm | Attempted | Completed | Passed |
|---|---|---|---|---|
| oakridge-dbos-context-defaults | baseline | 0 | 0 | 0 |
| oakridge-dbos-dispatch-handler | baseline | 0 | 0 | 0 |
| oakridge-dbos-pointer-root | baseline | 0 | 0 | 0 |
| oakridge-dbos-stage-pass-through | central | 5 | 5 | 0 |
| oakridge-dbos-stage-pass-through | cross_module | 5 | 5 | 0 |
| oakridge-dbos-stage-pass-through | modular | 5 | 5 | 0 |
| oakridge-dbos-stage-pass-through | plugin | 5 | 4 | 0 |

## Verification behavior

Agent self-assessment is shown only beside the independent evaluator verdict. An unavailable verdict remains unavailable.

| Attempt | Agent assessment | External verdict | Agreement |
|---|---|---|---|
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:central:w0 | complete | unavailable | unavailable |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:cross_module:w0 | complete | unavailable | unavailable |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:modular:w0 | complete | unavailable | unavailable |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:plugin:w0 | unavailable | unavailable | unavailable |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:cross_module:w1 | complete | unavailable | unavailable |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:modular:w1 | complete | unavailable | unavailable |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:plugin:w1 | complete | unavailable | unavailable |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:central:w1 | complete | unavailable | unavailable |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:modular:w2 | complete | unavailable | unavailable |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:plugin:w2 | complete | unavailable | unavailable |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:central:w2 | complete | unavailable | unavailable |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:cross_module:w2 | complete | unavailable | unavailable |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:plugin:w3 | complete | unavailable | unavailable |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:central:w3 | complete | unavailable | unavailable |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:cross_module:w3 | complete | unavailable | unavailable |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:modular:w3 | complete | unavailable | unavailable |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:central:w4 | complete | unavailable | unavailable |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:cross_module:w4 | complete | unavailable | unavailable |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:modular:w4 | complete | unavailable | unavailable |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:plugin:w4 | complete | unavailable | unavailable |

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
| harness_or_provider_failure | 19 |
| wrong_abstraction_or_plan | 1 |

Cost coverage is reported separately from implementation effects. Unpriced local usage is never treated as zero cost or ranked against priced usage.

| Arm | Priced | Unavailable | Uncertain | Observed cost |
|---|---|---|---|---|
| baseline | 0 | 0 | 0 | unpriced |
| central | 5 | 0 | 0 | 0.3591 USD |
| cross_module | 5 | 0 | 0 | 0.3682 USD |
| modular | 5 | 0 | 0 | 0.3588 USD |
| plugin | 5 | 0 | 0 | 0.3658 USD |

## Secondary measures

Scope of diff and unnecessary changed paths come from offline `assay code-metrics` comparison of the committed fixture tree with the patched tree. The expected path set is declared per task; an unmeasured path count stays unavailable.

| Attempt | Changed paths | Unnecessary paths | Duration s | Prompt tokens | Completion tokens | Tool calls | Files inspected | Retries |
|---|---|---|---|---|---|---|---|---|
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:central:w0 | 1 | 0 | 50.524809 | 73275.0 | 1669.0 | 10 | 0 | 0 |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:cross_module:w0 | 2 | 1 | 71.139785 | 79088.0 | 2134.0 | 18 | 7 | 0 |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:modular:w0 | 1 | 0 | 51.836108 | 72791.0 | 1821.0 | 15 | 7 | 0 |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:plugin:w0 | 2 | 0 | 97.546906 | 66800.0 | 1821.0 | 17 | 9 | 0 |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:cross_module:w1 | 2 | 1 | 63.468604 | 91094.0 | 2016.0 | 11 | 0 | 0 |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:modular:w1 | 1 | 0 | 66.598422 | 89715.0 | 2363.0 | 18 | 7 | 0 |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:plugin:w1 | 2 | 0 | 96.883566 | 98356.0 | 3549.0 | 23 | 8 | 0 |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:central:w1 | 1 | 0 | 59.188078 | 86132.0 | 2090.0 | 18 | 8 | 0 |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:modular:w2 | 1 | 0 | 54.809782 | 69907.0 | 1842.0 | 15 | 7 | 0 |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:plugin:w2 | 2 | 0 | 57.490805 | 59504.0 | 1898.0 | 17 | 7 | 0 |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:central:w2 | 1 | 0 | 52.882938 | 78581.0 | 1989.0 | 17 | 9 | 0 |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:cross_module:w2 | 2 | 1 | 65.448274 | 87609.0 | 2292.0 | 19 | 9 | 0 |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:plugin:w3 | 2 | 0 | 95.87132 | 124457.0 | 3243.0 | 24 | 8 | 0 |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:central:w3 | 1 | 0 | 58.632796 | 73303.0 | 1847.0 | 16 | 8 | 0 |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:cross_module:w3 | 2 | 1 | 65.37717 | 81593.0 | 2234.0 | 15 | 5 | 0 |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:modular:w3 | 1 | 0 | 54.985952 | 61095.0 | 1924.0 | 15 | 6 | 0 |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:central:w4 | 1 | 0 | 84.231662 | 85815.0 | 1902.0 | 16 | 7 | 0 |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:cross_module:w4 | 2 | 1 | 66.564556 | 86737.0 | 2235.0 | 10 | 1 | 0 |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:modular:w4 | 1 | 0 | 58.506488 | 73124.0 | 1879.0 | 13 | 4 | 0 |
| 502ff08d-b325-4cd7-a309-85042460265c:oakridge-dbos-stage-pass-through:plugin:w4 | 2 | 0 | 54.672629 | 52557.0 | 1943.0 | 16 | 7 | 0 |

## Scenario outcomes

This table counts primary attempts only, including invalid and unevaluable primary attempts. Other tables count all retained attempts. In the CSV and JSON ledgers, `retry_of` is `none` for a primary attempt and names the original attempt for a retry.

Intervals use the Wilson score method at alpha 0.05. They describe execution variability on a fixed task, rather than sampling error over tasks. The fixture roster shown here lists 4 qualified scenarios; the planned pilot has fifteen attempts, five repeats on each of three fixed tasks. Only retained planned coordinates count as attempts. The repeats are not fifteen independently sampled tasks.

| Scenario | Planned | Missing | No candidate | Operational yield | Primary task success | Conditional correctness | Invalid | Unevaluable |
|---|---|---|---|---|---|---|---|---|
| oakridge-dbos-context-defaults | 0 | 0 | 0 | 0/0 (unavailable; 95% interval unavailable) | 0/0 (unavailable; 95% interval unavailable) | 0/0 (unavailable; 95% interval unavailable) | 0 | 0 |
| oakridge-dbos-dispatch-handler | 0 | 0 | 0 | 0/0 (unavailable; 95% interval unavailable) | 0/0 (unavailable; 95% interval unavailable) | 0/0 (unavailable; 95% interval unavailable) | 0 | 0 |
| oakridge-dbos-pointer-root | 0 | 0 | 0 | 0/0 (unavailable; 95% interval unavailable) | 0/0 (unavailable; 95% interval unavailable) | 0/0 (unavailable; 95% interval unavailable) | 0 | 0 |
| oakridge-dbos-stage-pass-through | 20 | 0 | 0 | 0/20 (0.00; 95% interval 0.00-0.16) | 0/0 (unavailable; 95% interval unavailable) | 0/0 (unavailable; 95% interval unavailable) | 0 | 20 |

## Terminal causes and measurement coverage

| Scenario | Terminal causes | Duration measured | Tool use measured | Tokens measured | Cost priced |
|---|---|---|---|---|---|
| oakridge-dbos-context-defaults | unavailable | 0/0 | 0/0 | 0/0 | 0/0 |
| oakridge-dbos-dispatch-handler | unavailable | 0/0 | 0/0 | 0/0 | 0/0 |
| oakridge-dbos-pointer-root | unavailable | 0/0 | 0/0 | 0/0 | 0/0 |
| oakridge-dbos-stage-pass-through | no_tool_call: 1/20, normal_submission: 19/20 | 20/20 | 20/20 | 20/20 | 20/20 |

## Interpretation

These scenario results do not isolate a code-shape effect. The fixture roster alone supplies no implementation effect.
