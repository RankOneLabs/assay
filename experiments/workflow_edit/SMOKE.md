# Workflow edit smoke qualification

The completed qualification used the pinned, network-disabled smoke image and the local Smithers route. The fixture remains excluded from Part 2 populations.
The measured cells were dispatched directly through the Pier repository-agent client and local Smithers; they were not an Assay `execute_plan` study run. The ceiling probes below exercised Assay's production `AdmissionLedger` separately.

## Artifact binding

`qualify_local.py` authored the artifact manifest over the observed offline container files. Its manifest digest is `sha256:eadc54eb67105b18d1110a5e7704a2385e06257ab27c557523945b72b086a5a7`; the observed tree digest is `sha256:430aa657221810315c5e65a54bab86cbe335f21e8be41da93b34dc792a859e8f` (client: `qualify_local.py`).

## Container and package footprint

- Docker writable layer: 2732032 bytes (`docker inspect`).
- Docker memory limit: 1073741824 bytes (`docker inspect`).
- Docker PID limit: 64 (`docker inspect`).
- Peak memory: 136830976 bytes (Docker cgroup `memory.peak`, read by the Pier container client).
- Peak PIDs: 15 (Docker cgroup `pids.peak`, read by the Pier container client).
- Package: 4 files and 6763 UTF-8 bytes (Pier model trial package snapshot). Pier defaults are 200 files and 1000000 bytes, leaving 196 files and 993237 bytes of headroom (Pier package validator); the wf-06 arm-specific limits are not configured in this checkout.

The manifest's hidden-test, patch, and rubric references remain smoke-only placeholders; the fixture cannot enter a study population.

## Model and dispatch measurements

- Completed dispatches: 20 of 20; failure rate 0% (Pier trial records and successful tool/test output).
- Nonfatal failed tool calls: 20 (Pier container tool output); these were attempts to invoke `submit_output` as a shell command before the model used the proper tool.
- Model requests: 40; prompt tokens 27479, completion tokens 4947 (Smithers worker task usage).
- Mean wall time from model acceptance: 3.473 seconds; mean queue latency: 0.070 seconds (Smithers dispatch timestamps).
- Paid route reachable: false; paid cells: 0 (Pier route assertion: `smithers-local`, no OpenRouter key).
- Admission halts: `budget_exhausted` and `ceiling_exhausted` (Assay `AdmissionLedger` qualification probes).
- Forced dropped-response re-dispatch: one Smithers job ID `33848b12-6f3c-4012-ab50-675cd3542cde` and one completion (Smithers dispatch API idempotency probe).
- Missing billing: `uncertain`, amount absent (Assay workflow-edit bridge accounting over Smithers worker usage).
- An earlier preflight command failed under the read-only runtime when npm tried to chmod a linked tool. The measured run used `npm ci --offline --no-bin-links`; every install/typecheck/test command exited successfully (Pier container tool output).

| Smithers job ID | Prompt tokens (Smithers worker) | Completion tokens (Smithers worker) | Wall s from acceptance (Smithers dispatch) | Queue s (Smithers dispatch) | Cell peak memory bytes (Docker cgroup) | Cell peak PIDs (Docker cgroup) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `e8c2c666-c2b5-4680-b9ca-4c44f13a7eec` | 493 | 143 | 35.710 | 0.074 | 134340608 | 15 |
| `8f81b70d-cb80-4064-ab66-d582167b93c7` | 881 | 23 | 0.683 | 0.063 | 134340608 | 15 |
| `94d98c8d-9f75-4168-8822-c5e66f976a54` | 493 | 144 | 2.987 | 0.038 | 132464640 | 15 |
| `b2f15329-a367-447f-a236-0a10e0e03649` | 881 | 142 | 2.578 | 0.091 | 132464640 | 15 |
| `8ae2d408-b526-4a00-b0e7-40e2a9d78787` | 493 | 144 | 2.941 | 0.079 | 134164480 | 15 |
| `c6d478f1-37f3-4e52-bc66-efdbab81f9d1` | 881 | 142 | 3.471 | 0.075 | 134164480 | 15 |
| `5155bf23-7c25-4848-9918-157a5ed4928b` | 493 | 144 | 2.701 | 0.036 | 130461696 | 15 |
| `01d71f6c-baff-4a4d-a0f6-35915831e904` | 881 | 142 | 2.944 | 0.086 | 130461696 | 15 |
| `fbfe72e9-a2b3-409a-b3af-d879a65c5541` | 493 | 144 | 2.546 | 0.061 | 130465792 | 15 |
| `83d1ca50-301a-4253-a7f0-d219bffcc543` | 881 | 142 | 3.457 | 0.058 | 130465792 | 15 |
| `74ea0cd4-fa55-4d1f-87ce-9432ca00320c` | 493 | 144 | 3.464 | 0.059 | 134328320 | 15 |
| `5f03956c-c186-41bc-b0c3-0c420b5b6065` | 881 | 23 | 1.287 | 0.084 | 134328320 | 15 |
| `c673b9e1-8311-4308-9d92-339c9168597f` | 493 | 143 | 2.865 | 0.070 | 132263936 | 15 |
| `edac06a9-b8e1-49ab-bc50-39054d4cd3b6` | 881 | 142 | 2.813 | 0.076 | 132263936 | 15 |
| `b715ebd6-5fbe-451f-9450-f37cae79b7b9` | 493 | 142 | 3.046 | 0.094 | 133337088 | 15 |
| `6727c0b8-cbba-4309-8f39-6107107be7b9` | 880 | 23 | 0.912 | 0.074 | 133337088 | 15 |
| `b86250de-c5de-4a29-823c-08e85eed7559` | 493 | 142 | 3.043 | 0.049 | 134529024 | 15 |
| `2ea5b36d-7e89-401b-b0cc-ff22155ae10f` | 881 | 32 | 0.674 | 0.055 | 134529024 | 15 |
| `c07a123b-b6fc-48cc-ac71-5fef04abb51e` | 493 | 143 | 2.704 | 0.053 | 134742016 | 15 |
| `6b459c3e-b44e-4c4f-9371-39713741b00a` | 881 | 142 | 3.063 | 0.072 | 134742016 | 15 |
| `048786a5-3df3-48d1-9069-dfa8f0ef9a47` | 493 | 144 | 2.968 | 0.078 | 133812224 | 15 |
| `ebfff36d-e782-43de-95dd-0a71bc271583` | 881 | 142 | 2.611 | 0.055 | 133812224 | 15 |
| `5dccf2e7-2b22-42e0-8021-2d1ec43ffe7c` | 493 | 143 | 2.528 | 0.086 | 136110080 | 15 |
| `6c227155-2518-4c9c-b606-30f17403ddf6` | 881 | 32 | 1.511 | 0.075 | 136110080 | 15 |
| `17f87871-c57f-4907-8fad-e7b428242085` | 493 | 143 | 3.088 | 0.057 | 136830976 | 15 |
| `31e901fe-22a6-47c9-8cef-e5d03023cc28` | 881 | 142 | 3.162 | 0.083 | 136830976 | 15 |
| `7c22747e-e40d-40c6-bf05-dd6d496ef84b` | 493 | 144 | 3.361 | 0.079 | 133382144 | 15 |
| `6ca4e88b-8578-4457-baf3-720e48e436b6` | 881 | 32 | 1.383 | 0.085 | 133382144 | 15 |
| `26f96467-c022-45dd-84d1-fd77036bdfe7` | 493 | 144 | 2.999 | 0.053 | 132800512 | 15 |
| `321a9a18-ae9d-4e75-a817-3c4911120c1b` | 881 | 142 | 3.580 | 0.081 | 132800512 | 15 |
| `39092133-aab8-4ecd-a342-544c0b565bce` | 493 | 144 | 2.770 | 0.057 | 132382720 | 15 |
| `13ddd10f-3b4b-4618-ae14-ab3758683842` | 881 | 32 | 1.512 | 0.111 | 132382720 | 15 |
| `263beb16-d0ec-4d1d-a3b1-31bf62b88aa5` | 493 | 144 | 3.041 | 0.051 | 134840320 | 15 |
| `a571720e-fb76-4b93-8ab4-3802ce6c3cf9` | 881 | 142 | 2.655 | 0.082 | 134840320 | 15 |
| `a014166c-20f0-4be5-bbbd-b28712123440` | 493 | 144 | 2.569 | 0.044 | 134258688 | 15 |
| `c1ed412b-bbe7-481a-a4b9-7fcfcfc002ff` | 881 | 142 | 2.812 | 0.088 | 134258688 | 15 |
| `eada3478-baaf-4beb-aff6-e51924c4335d` | 493 | 143 | 2.899 | 0.082 | 135163904 | 15 |
| `3cb82520-df57-4334-94b8-1d500d329aa3` | 881 | 160 | 3.509 | 0.057 | 135163904 | 15 |
| `31bb69bb-96ca-4c3f-862c-b4fcfc2772c8` | 493 | 142 | 2.579 | 0.073 | 132837376 | 15 |
| `170d9969-2444-418b-893d-2af5f9e07926` | 881 | 160 | 3.510 | 0.076 | 132837376 | 15 |
