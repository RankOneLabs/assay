# Workflow edit smoke qualification

Qualification is incomplete. The no-model container gate and the harness
binding gate produced evidence. A multi-request Smithers/Pier model trial and
the required 20 live dispatches have not run, so no complete section 6
measurement set or replacement bounds are published here.

## Gate 1: offline container

The observing client was the Docker CLI. The trial ran `npm ci --offline`, a
strict TypeScript typecheck, compilation, and a Node test with `--network none`.
`docker inspect --size assay-wf12-smoke-observed` reported a zero exit code,
image `sha256:fb9dc69ddb4bc25b590b8e45ee0bccb9dd30c3e6bb9e5d49dcddb66487b63f35`,
and a writable container layer of **2,732,032 bytes**. The same inspection
reported a configured memory ceiling of **1,073,741,824 bytes** and a PID
ceiling of **64**. These ceilings are configuration observations, not peak
memory or peak PID footprint. The package snapshot's file and byte counts
are recorded in the fixture README, where their source is the repository
validator rather than Docker inspection.

## Gate 2: artifact binding

`qualify_local.py` read the container inspection and logs, then authored the
artifact manifest over the observed files. It reported 10 artifact entries,
manifest digest
`sha256:eadc54eb67105b18d1110a5e7704a2385e06257ab27c557523945b72b086a5a7`,
and tree digest
`sha256:430aa657221810315c5e65a54bab86cbe335f21e8be41da93b34dc792a859e8f`.
The candidate did not supply the manifest.

## Gate 3: model loop and dispatch

The bridge now has a zero-paid qualification route through local Smithers
(`qwen-coder-32b` on `mcbain`) and a test proving it cannot reach OpenRouter.
The observing clients for a completed run would be the Smithers dispatch
API, its worker task endpoint for token counts, the Pier repository-agent
loop, and Docker inspection. A real attempt on 2026-10-14 entered the Pier
loop with that route but stopped during quota preparation with
`AgentLoopError: storage_mount`: this host's `sudo -n mount` requires a
password. No model request or cell completed in that attempt. The existing
image ID still matches `MANIFEST.json`; it was not rebuilt.

The wf-06 arm worker configurations still do not declare repository file or
byte limits in this checkout. The 4-file, 6,763-byte slice therefore remains
compared against Pier's defaults in the fixture README; that comparison is
not being presented as an arm-configured margin. The smoke manifest's hidden
test, patch, and rubric references remain placeholders and the fixture stays
excluded from every study population by `validate_worker_grid`.

Per-turn prompt and completion tokens, wall time from Smithers acceptance,
queue latency, failure rate, peak memory and PID usage, and package size as a
Docker-inspected quantity remain unmeasured. The 20 live end-to-end dispatches,
both ceiling halt kinds, forced dropped-response re-dispatch, and missing
billing observation are also outstanding. The publication guard in
`workflow_edit.smoke` rejects host-driver evidence, a single model request,
missing dispatches, reachable paid routes, and absent halt/idempotency/billing
proof. It does not write a completed report from this partial evidence.
