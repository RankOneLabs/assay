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
- the exact Pier commit (see "Known gap" below);
- the resolved bridge image digest, produced by `Dockerfile` and recorded by
  whatever deploys the image (not by this repo, which has no registry
  access).

`runtime.py` never installs a package, resolves a dependency, or writes to a
pricing map while serving a trial — the lifecycle tests in
`tests/test_trial_lifecycle.py` assert this by spying on subprocess/network
calls during `PierTrialClient.create`/`TrialHandle.run`, not by trusting a
comment.

## Known gap: no pinned Pier revision

There is no `pier` package resolvable from this environment: it is not on
PyPI, and there is no `Pier` repository under the `RankOneLabs` GitHub org
this checkout otherwise pulls pinned dependencies from (see the `legacy`
extra in the root `pyproject.toml` for the pattern this project follows,
`jig @ git+https://github.com/RankOneLabs/jig.git@<sha>`). Rather than
inventing a fake upstream to pin, this project defines `PierTrialClient` and
`TrialHandle` (`protocol.py`) as the exact contract a real Pier client must
satisfy — `create()` called exactly once per request, verification disabled,
one `TrialResult` with observed (not declared) `EffectiveEnforcement`.
`runtime.py` is written entirely against that protocol and is exercised in
tests with a fake implementation. When the real Pier package is reachable,
wiring it in is: add the pinned git dependency to `pyproject.toml`, `uv lock`,
and pass its client through the `PierTrialClient` boundary. This gap is
recorded as a `known_issue` on the build result.

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
