# assay-pier-bridge

Isolated Pier/mini-swe-agent bridge. This project is deliberately not part of
the `assay` workspace: it carries its own `pyproject.toml` and `uv.lock` so
the bridge image's dependency set — and therefore its build — is locked
independently of the rest of Assay. Nothing here imports `assay`, and
nothing in `assay` imports this package; the two sides only share a wire
contract (`TrialRequest`/`TrialResult`, see `src/assay_pier_bridge/protocol.py`)
that a sealed Harbor package built by `assay.pier_packaging` is handed across.

## Runtime identity

A bridge sync pins three things as runtime identity inputs (recorded as
`BridgeIdentity` in `protocol.py`) and none of them may change while trials
are being served:

- the exact `mini-swe-agent` commit (`a83fcae82d2a08f0ee0c688f9d137b3566c097f8`,
  tag `v2.4.6` of `SWE-agent/mini-swe-agent`), pinned in `pyproject.toml` as a
  git dependency and resolved into `uv.lock`;
- the exact Pier version (see "Pier revision" below);
- the resolved bridge image digest, produced by `Dockerfile` and recorded by
  whatever deploys the image (not by this repo, which has no registry
  access). A local build against this checkout's `uv.lock` produced
  `sha256:b3e07726d3e92731c1ac1f934d27457a6545a52660af484fd67fb092cf09dc3f`
  (`docker build -t assay-pier-bridge:test .`); a fresh build from the same
  lock reproduces the same dependency set, but the image ID itself is not
  guaranteed byte-stable across builder/base-image updates the way the lock
  digest is — treat the lock digest, not the image ID, as the durable
  identity input. `docker run --rm --network none assay-pier-bridge:test`
  starts and exits 0 with no network access at all, which is the concrete
  check that the image never reinstalls or resolves anything at trial time.

`runtime.py` never installs a package, resolves a dependency, or writes to a
pricing map while serving a trial — the lifecycle tests in
`tests/test_trial_lifecycle.py` assert this by spying on subprocess/network
calls during `PierTrialClient.create`/`TrialHandle.run`, not by trusting a
comment.

## Pier revision

The real Pier package is not named `pier` on PyPI and is not published under
the `RankOneLabs` org this checkout otherwise pulls pinned dependencies from
(see the `legacy` extra in the root `pyproject.toml`,
`jig @ git+https://github.com/RankOneLabs/jig.git@<sha>`) — an earlier pass
searched for exactly those two things and, finding neither, recorded a
`known_issue` and shipped `PierTrialClient`/`TrialHandle` as a local
`Protocol` only. It is in fact published to PyPI as `datacurve-pier`
(source at `github.com/datacurve-ai/pier`, which itself publishes no source
repository — there is a third-party single-commit mirror at
`github.com/maxi-tools/pier` calling itself "the pinnable copy", but this
project pins the real PyPI distribution rather than an unverifiable mirror).
`pyproject.toml` now pins `datacurve-pier==0.3.1`, resolved into `uv.lock`
with hash pins — the exact version plus the lock's hashes is this
dependency's durable identity, since Pier itself publishes no commit to pin
against.

The real package's API matches this project's `PierTrialClient` design
closely: `pier.trial.trial.Trial.create(config)` is a real classmethod
(`Trial(...)` construction is explicitly deprecated in favor of it), and
`mini-swe-agent` is a first-class supported agent (`AgentName.MINI_SWE_AGENT`).
`pier_adapter.py` maps a `TrialRequest` onto a real `pier.models.trial.config.TrialConfig`
and writes the on-disk task directory Pier's `Task` loader expects;
`tests/test_pier_adapter.py` proves both against the real installed
package's pydantic models and loader, not a fake. Two things worth noting
that this pass verified directly against the real schema:

- verification is disabled via the real `VerifierConfig.disable` field on
  the trial-level config (not a task.toml setting), so it overrides whatever
  a task on disk declares — exactly the "upstream verification disabled"
  key decision;
- Pier's `NetworkPolicyFieldsMixin` only supports `network_mode` values
  `no-network` and `public` — `allowlist` is explicitly rejected at parse
  time ("not supported by pier yet"). There is no way to ask Pier's own
  environment for this project's `egress-openrouter-only` policy. The agent
  phase must run with `no-network`, and the guarded OpenRouter call must be
  made by the bridge process itself, outside the agent's sandbox — matching
  the "guarded route" key decision, and confirming it was the right call
  independent of this discovery.

**What is still not wired end to end**, and is recorded as a `known_issue`
rather than guessed at: Pier owns its own container lifecycle through an
`EnvironmentFactory` (docker/modal/daytona) that builds a task-specific
image from an `environment/Dockerfile` inside the task directory — a
second, independent image-build surface from the one this project already
locked in `Dockerfile` and drives directly in `container.py`. Reconciling
"one bridge image reused across every trial" (this project's model) with
"one environment image per task, built by Pier" (Pier's model) is a real
architectural decision for whoever picks this up next, not a detail to
paper over; `pier_adapter.py` builds and validates the config and task
directory but does not call `Trial.create`/`Trial.run` against a live
docker/modal backend.

## Guarded model route

`provider.py` implements `GuardedOpenRouterClient`, a narrow httpx-based
client that only ever speaks to `POST https://openrouter.ai/api/v1/chat/completions`
using the exact pinned route (`anthropic/claude-3-haiku` via
`amazon-bedrock`, mirroring `assay.adapters.openrouter_policy.HAIKU_BEDROCK`
in the root project — duplicated here rather than imported, so this package
has no dependency edge back onto `assay`). It makes zero retries, validates
the response's `model`/`provider` identity and `usage.cost` before returning,
enforces the single-tool submission protocol, and fails closed (raises) on
any response with an unrecognized top-level field, a different route, or a
missing/invalid cost.

## Sealed package boundary

The bridge never reads a realization directory or repository root. It is
handed a sealed package built by `assay.pier_packaging` in the root project:
`instruction.md`, the selected arm's repository under `/workspace` (read
only), and the submission contract — nothing else. `/submission` and
`/scratch` are fresh, writable, per-trial mounts.

## Commands

```bash
uv sync --group dev      # install locked deps
uv run pytest            # protocol, provider, and lifecycle tests
```
