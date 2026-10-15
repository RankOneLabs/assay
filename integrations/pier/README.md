# assay-pier-bridge

An isolated bridge between Assay and the [Pier](https://pypi.org/project/datacurve-pier/)
/ mini-swe-agent execution stack. It has its own `pyproject.toml` and `uv.lock`
so the bridge image's dependencies are locked independently of Assay. The two
sides do not import each other; they share only the wire contract
(`TrialRequest`/`TrialResult` in `src/assay_pier_bridge/protocol.py`), across
which Assay hands a sealed package built by `assay.pier_packaging`.

```bash
uv sync --group dev
uv run pytest
```

Container and trial-lifecycle tests skip when no Docker daemon is reachable.

## Runtime identity

Three inputs, recorded as `BridgeIdentity` in `protocol.py`, must not change
while trials are being served:

- **mini-swe-agent** — commit `a83fcae82d2a08f0ee0c688f9d137b3566c097f8`
  (tag `v2.4.6`), pinned in `pyproject.toml` and resolved into `uv.lock`.
- **Pier** — see [Pier revision](#pier-revision).
- **Bridge image digest** — built from `Dockerfile` and read from that build
  with `docker image inspect --format '{{.Id}}' assay-pier-bridge:test`.
  `identity.bind_bridge_identity(manifest, image_ref)` fills this field from
  inspection and raises `ImageDigestMismatchError` if a manifest declares a
  different digest. Rebuilds may have different image IDs, even with the same
  dependency locks, and therefore form different fixtures.

The image adds Node v22.21.1 and bun 1.3.13 from digest-pinned upstream images
and installs the workflow edit fixture's locked dependencies (TypeScript 5.9.3,
zod 4.4.3, @types/bun 1.3.13, the versions oakridge-dbos locks at its pinned
commit) from [`workflow_edit/package.json`](workflow_edit/package.json) and
[`workflow_edit/package-lock.json`](workflow_edit/package-lock.json) during the
build. The complete locked `node_modules` tree is copied into the final image
at `/opt/workflow_edit` and linked at `/node_modules`, so module and `@types`
resolution from `/workspace` (agent) or `/tmp/workflow` (evaluator) reaches it
without anything being installed into, or linked from, a candidate tree. npm
is omitted from the final image because dependency installation is a build
step. Any rebuild, including one caused by a bridge source change, is a new
fixture image; the shared Dockerfile means it is also a new image for the DRY
Pier profile's pin.

The repository agent (`agent_loop.py`, `repository_trial.py`) runs on the
host and drives a network-disabled tool container from this image with
Docker-enforced tmpfs quotas; `experiments/workflow_edit/bridge.py` is the one
place it meets Assay.
Build the image once with
`docker build -t assay-pier-bridge:qualify-local integrations/pier`, then read
its digest with `docker image inspect --format '{{.Id}}'
assay-pier-bridge:qualify-local` and record it as
`pier_experiment.PIER_BRIDGE_IMAGE_DIGEST`. The qualification script uses the
already-built image: it binds the observed digest against that pin and
reinspects the image immediately before publishing the inventory. A stale
pin fails with `ImageDigestMismatchError`.

`docker run --rm --network none assay-pier-bridge:test` starts and exits 0,
confirming the image never installs or resolves anything at trial time.
`tests/test_container_lifecycle.py` also runs `node --version` and
`tsc --version` in a network-disabled container and checks that the locked
TypeScript tree is present and npm is absent.

## Pier revision

Pier is published on PyPI as `datacurve-pier`. `pyproject.toml` pins
`datacurve-pier==0.3.1` with hash pins in `uv.lock`; since Pier publishes no
source commit, the version plus hashes is its identity.

`pier_adapter.py` maps a `TrialRequest` onto Pier's `TrialConfig` and writes
the task directory Pier's loader expects; `tests/test_pier_adapter.py` checks
both against the installed package. Two constraints follow from Pier's schema:

- Upstream verification is disabled with the trial-level
  `VerifierConfig.disable`, which overrides anything a task declares.
- Pier's `network_mode` supports only `no-network` and `public`. The agent
  therefore runs with `no-network`, and the model call is made by the bridge
  outside the sandbox (see below).

**Limitation:** Pier builds a per-task environment image through its own
`EnvironmentFactory`, while this bridge reuses one locked image driven by
`container.py`. These are not yet reconciled, so `pier_adapter.py` builds and
validates the config and task directory but does not call
`Trial.create`/`Trial.run` against a live backend.

## Guarded model route

`provider.py`'s `GuardedOpenRouterClient` speaks only to
`POST https://openrouter.ai/api/v1/chat/completions` on one pinned route
(`anthropic/claude-3-haiku` via `amazon-bedrock`, mirroring
`assay.adapters.openrouter_policy.HAIKU_BEDROCK`). It makes no retries,
validates the response's model, provider, and `usage.cost`, enforces the
single-tool submission protocol, and fails closed on any unexpected field,
route, or missing cost.

The trial container always runs with `--network none`, so the guarded call runs
on the host: `host_driver.GuardedCompletionTrialClient` calls
`__main__.run_one_cell` directly in the bridge process. `DockerTrialClient` in
`container.py` is the sandbox lifecycle harness, covering mounts, uid, resource
limits, and teardown.

## Sealed package boundary

The bridge never reads a realization directory or repository root. It receives
only `instruction.md`, the selected arm's repository at `/workspace` (read-only),
and the submission contract. `/submission` and `/scratch` are fresh, writable,
per-trial mounts.
