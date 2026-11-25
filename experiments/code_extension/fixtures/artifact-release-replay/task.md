# Let reviewers take their time over gated artifacts

This repository is `oakridge-dbos`, Oakridge's DBOS workflow engine, at the root of an
Oakridge checkout. A stage runs one execution workflow per unit
(`artifactContractExecutionWorkflow` in `oakridge-dbos/src/workflows/executor-topology.ts`),
coordinated by `productionStageWorkflow` in `production-topology.ts`. The execution starts an
agent session through its executor adapter, receives the artifacts the agent emits, and holds
gated outputs at their approval gate until a reviewer decides.

## The problem

An execution returns as soon as the terminal observer reports that its executor has ended. If
the agent emitted an artifact into an approval gate and its session then ended, the execution
has already returned with that output missing by the time the reviewer gets to it. The stage
coordinator fails the unit with `required_output_missing`, and the reviewer's approval is
delivered to a workflow that is no longer listening, so the artifact is never released.

Reviewers work at human pace, and an agent session usually ends long before the review does.

## What to change

1. An artifact emitted into a gate or a handoff can still be approved after its agent's session
   has ended. That approval releases the artifact and completes the unit, exactly as an approval
   given while the session was still up would.
2. When the agent's session ends and an output the unit owes has never been emitted, the unit
   fails as missing output promptly, as it does now. It does not wait on reviews of the unit's
   other outputs first, since the unit cannot be satisfied.
3. Everything else about executions, gates, handoffs and the stage coordinator behaves as
   before.

Add tests for the new behaviour next to the existing ones in `oakridge-dbos/tests/`.
