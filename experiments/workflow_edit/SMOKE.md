# Workflow edit smoke qualification

The completed qualification used the pinned, network-disabled smoke image and the local Smithers route. The fixture remains excluded from Part 2 populations.
The measured cells were dispatched directly through the Pier repository-agent client and local Smithers; they were not an Assay `execute_plan` study run. The ceiling probes below exercised Assay's production `AdmissionLedger` separately.

## Artifact binding

`qualify_local.py` authored the artifact manifest over the observed offline container files. Its verified manifest digest is `sha256:fd2a6ad02cfd7da1f243b220cf45be05eaf68841ecf9e0b2e23b1e261ed23638`; the observed tree digest is `sha256:430aa657221810315c5e65a54bab86cbe335f21e8be41da93b34dc792a859e8f` (client: `qualify_local.py` and `docker inspect`).

## Container and package footprint

- Docker writable layer: 2732032 bytes (`docker inspect`).
- Docker memory limit: 1073741824 bytes (`docker inspect`).
- Docker PID limit: 64 (`docker inspect`).
- Peak memory: 136142848 bytes (Docker cgroup `memory.peak`, read by the Pier container client).
- Peak PIDs: 15 (Docker cgroup `pids.peak`, read by the Pier container client).
- Package: 4 files and 6763 UTF-8 bytes (Pier model trial package snapshot). Pier defaults are 200 files and 1000000 bytes, leaving 196 files and 993237 bytes of headroom (Pier package validator); the wf-06 arm-specific limits are not configured in this checkout.

The manifest's hidden-test, patch, and rubric references remain smoke-only placeholders; the fixture cannot enter a study population.

## Model and dispatch measurements

- Completed dispatches: 20 of 20; failure rate 0% (Pier trial records and harness-controlled install/typecheck/test results).
- Nonfatal failed tool calls: 20 (Pier container tool output); these were attempts to invoke `submit_output` as a shell command before the model used the proper tool.
- Model requests: 40; prompt tokens 27473, completion tokens 4947 (Smithers worker task usage).
- Mean wall time from model acceptance: 3.604 seconds; mean queue latency: 0.893 seconds (Smithers dispatch timestamps).
- Paid route reachable: false; paid cells: 0 (Pier route assertion: `smithers-local`, no OpenRouter key).
- Admission halts: `budget_exhausted` and `ceiling_exhausted` (Assay `AdmissionLedger` qualification probes).
- Forced dropped-response re-dispatch: one Smithers job ID `33848b12-6f3c-4012-ab50-675cd3542cde` and one completion (Smithers dispatch API idempotency probe).
- Missing billing: `uncertain`, amount absent (Assay workflow-edit bridge accounting over Smithers worker usage).
- An earlier preflight command failed under the read-only runtime when npm tried to chmod a linked tool. The measured run used `npm ci --offline --no-bin-links`; every install/typecheck/test command exited successfully (Pier harness check events).

| Smithers job ID | Prompt tokens (Smithers worker) | Completion tokens (Smithers worker) | Wall s from acceptance (Smithers dispatch) | Queue s (Smithers dispatch) | Cell peak memory bytes (Docker cgroup) | Cell peak PIDs (Docker cgroup) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `469f5e42-6e3b-422b-a0dd-fe10436d2983` | 493 | 143 | 40.108 | 32.885 | 132042752 | 15 |
| `dda31bfc-1f12-4e67-ac06-57eec3c30360` | 881 | 23 | 0.624 | 0.045 | 132042752 | 15 |
| `fd7fa542-9170-4d37-9d99-49a1b2d76db7` | 493 | 144 | 3.372 | 0.084 | 133697536 | 15 |
| `2335dfe8-921c-4c79-a18a-b3a86c5351bf` | 880 | 142 | 3.123 | 0.086 | 133697536 | 15 |
| `ecd2c8eb-97a9-41b6-a3a9-b92d9f262a7f` | 493 | 144 | 3.485 | 0.083 | 131059712 | 15 |
| `44245703-fa8c-4a3a-b513-332cb2eaaf0a` | 881 | 142 | 3.049 | 0.064 | 131059712 | 15 |
| `5d4310f4-533c-41c7-93de-856f44022ce6` | 493 | 144 | 2.853 | 0.093 | 133230592 | 15 |
| `d91e528a-bf88-4b63-b3bc-6b19c1330da3` | 882 | 142 | 3.471 | 0.082 | 133230592 | 15 |
| `355d1364-f175-4156-bd9e-76996fd7c72d` | 493 | 144 | 2.629 | 0.052 | 133292032 | 15 |
| `a57ed9e3-95fd-4141-82ef-89d5b14ed9d1` | 881 | 142 | 2.671 | 0.148 | 133292032 | 15 |
| `18a49a1f-5fbf-4936-a7ad-7a7088d8f3c0` | 493 | 144 | 2.613 | 0.083 | 134017024 | 15 |
| `ad4d6036-945d-46d7-9597-a84f0bb2c28b` | 880 | 23 | 1.308 | 0.068 | 134017024 | 15 |
| `89c0c269-122a-4f71-b8f5-2a31bbae11e1` | 493 | 143 | 2.688 | 0.056 | 133562368 | 15 |
| `35d1277b-d0f0-4cf1-a3b4-fe5aba50d630` | 881 | 142 | 3.027 | 0.097 | 133562368 | 15 |
| `0c9aca5e-b768-455d-9fff-fb649f2fffbb` | 493 | 142 | 2.528 | 0.089 | 135589888 | 15 |
| `f06d1dbf-efe2-4439-a158-1bb5874a6d83` | 881 | 23 | 0.793 | 0.084 | 135589888 | 15 |
| `1472e001-b408-42ca-b04d-b8692c73f986` | 493 | 142 | 3.110 | 0.051 | 131248128 | 15 |
| `dae68f8b-b8d1-472b-aea2-4fcad6815e03` | 880 | 32 | 1.456 | 0.077 | 131248128 | 15 |
| `8eedf1fe-4183-42e5-bcd6-a9bcca71d836` | 493 | 143 | 3.083 | 0.045 | 134942720 | 15 |
| `5d21b8ff-943a-4791-94e1-e6a4bedb6b0d` | 880 | 142 | 3.337 | 0.055 | 134942720 | 15 |
| `2d69001d-7a41-48af-9603-ba58d74f3e34` | 493 | 144 | 2.759 | 0.091 | 133554176 | 15 |
| `d828eb33-b517-45b1-84d0-c47928df9107` | 881 | 142 | 2.730 | 0.080 | 133554176 | 15 |
| `0acbfeb0-a3c4-4330-814d-e7d74084def6` | 493 | 143 | 3.525 | 0.037 | 133275648 | 15 |
| `42d5dad8-cace-4cae-b08b-378050af75a2` | 880 | 32 | 1.398 | 0.066 | 133275648 | 15 |
| `02a079ed-88ef-4310-8a94-ddbcfad8a72a` | 493 | 143 | 2.524 | 0.054 | 132177920 | 15 |
| `eaa4f954-98d3-43f4-94b1-73c43781cb0b` | 880 | 142 | 2.800 | 0.055 | 132177920 | 15 |
| `5efe2126-9df2-46ad-ad7b-9d532e5ca944` | 493 | 144 | 3.062 | 0.117 | 132526080 | 15 |
| `01e8e760-fd65-4d51-873d-d1c8303dc81d` | 881 | 32 | 0.656 | 0.050 | 132526080 | 15 |
| `8449a0bc-a571-4f78-ae3c-59c73bed51b8` | 493 | 144 | 3.308 | 0.089 | 133210112 | 15 |
| `c346ddb9-e59a-4c26-b422-9523106cffd1` | 880 | 142 | 3.352 | 0.045 | 133210112 | 15 |
| `d5f2e177-cab5-4b21-be26-c64ce52e77c9` | 493 | 144 | 3.564 | 0.075 | 132845568 | 15 |
| `fa978e59-64b2-421f-91db-fe0e4abde955` | 881 | 32 | 1.350 | 0.084 | 132845568 | 15 |
| `6a79d828-ce77-4701-9806-31f79a0fa995` | 493 | 144 | 3.085 | 0.090 | 131710976 | 15 |
| `e6715491-a61f-4ffc-992d-9f078d12b432` | 881 | 142 | 2.860 | 0.083 | 131710976 | 15 |
| `b172d58b-6592-48a3-a3d1-971b2585de1f` | 493 | 144 | 3.052 | 0.037 | 132435968 | 15 |
| `e67e1975-4783-4b9d-a065-4f61d56ebad6` | 881 | 142 | 2.664 | 0.056 | 132435968 | 15 |
| `410eadd7-c6b0-45a0-b2d2-afde10c636bf` | 493 | 143 | 2.681 | 0.084 | 135565312 | 15 |
| `92794832-a1a4-4f90-9e0a-d3f9dbbf3e7f` | 880 | 160 | 3.528 | 0.049 | 135565312 | 15 |
| `ff613ce8-5cfc-43d2-949b-a02338fbc5ad` | 493 | 142 | 2.714 | 0.103 | 136142848 | 15 |
| `e376dcf7-a2ac-4ebf-8e5d-dbf7901ee035` | 881 | 160 | 3.236 | 0.047 | 136142848 | 15 |
