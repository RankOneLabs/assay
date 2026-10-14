# Pier integration and qualification

Pier is the third-party (`datacurve-pier`) agent-execution provider Assay drives
through the isolated [`integrations/pier`](../integrations/pier/README.md)
bridge project. The bridge has its own lock and qualification script.

The trial envelope is `assay-pier-trial/0.3.0`. `/scratch` is a bind mount of
an ext4 filesystem image kept under the host trial run directory. The image's
filesystem capacity is the storage quota; Docker's memory cgroup is a separate,
higher ceiling. The host running `DockerTrialClient` needs noninteractive root
access for loop mounting and unmounting the image. A trial refuses to proceed
when inspection does not confirm the bind mount, quota, read-only root and
baseline, or declared network posture. The initial storage, memory, and PID
bounds are provisional pending `experiments/workflow_edit/SMOKE.md`.

The `egress-openrouter-only` and `toolchain-only` postures both run the
container with Docker networking disabled. `egress-lan-host-port` creates a
dedicated bridge network for the trial and installs per-interface host firewall
rules that allow TCP to the declared RFC1918 IPv4 address and port and drop other
traffic. The host needs noninteractive root access to manage those rules.

The authorized Pier worker configuration carries `max_repository_files` and
`max_repository_bytes` for the selected arm. `PierAdapter` passes both values
to `build_package` at dispatch, so editing library defaults cannot change a
plan's bound limits. It also carries the six named synthetic containment
sentinels; `gate_package` checks them after the package digest and mount-path
allowlist checks. Repository validation rejects paths over 4 KiB, segments
over 255 UTF-8 bytes, and names colliding after NFC normalization and case
folding.

`assay.fixture_manifest.FixtureManifest` is the versioned fixture identity
document. It records the checkpoint, path selection, lock digests, observed
runtime image digest, normalization diff, treatment inventory, per-arm trees,
transformation and equivalence versions, task prompt, and Smithers
`routing_config.yaml` digest. Hidden tests, reference and negative patches,
and rubric appear only as SHA-256 references. The exported schema is
`schemas/assay-fixture-manifest.schema.json`; `fixture_identity` hashes the
complete canonical document, so a changed image or routing digest changes
the fixture identity.

## Submission patch normalization

The writable trial working copy starts as a byte-for-byte copy of the selected
arm's immutable baseline. The host enumerates both trees after the agent stops;
the agent's list of edited files is trajectory data only. Paths are canonical
relative POSIX paths, sorted by their UTF-8 bytes. Each regular file has mode
`100644`; symlinks, special files, non-UTF-8 source and NUL bytes are rejected.
The baseline is checked against the sealed package again before diffing.

The captured patch is a Git unified diff with `diff --git`, `index`, `---`,
`+++`, and `@@` lines. Index values are full lowercase Git SHA-1 blob IDs,
with the all-zero ID on the absent side. Added and deleted files use
`new file mode 100644` or `deleted file mode 100644`. Context is three lines;
all patch metadata and separators use LF, with no timestamps. File content
line endings are preserved by the diff and a missing final newline is marked
with Git's `\\ No newline at end of file` marker. An unchanged tree has a
zero-byte patch and is a valid no-op submission. The final tree digest is
SHA-256 of the sorted sequence of `path UTF-8`, NUL, mode `100644`, NUL,
file bytes, NUL. Applying the patch to the arm baseline must reproduce that
digest. Evidence is read from the host-visible working copy before teardown.

For a workflow fixture, build the bridge image before finalizing its manifest,
then call `assay_pier_bridge.identity.bind_bridge_identity(manifest, image_ref)`.
It reads `docker image inspect --format '{{.Id}}'` and binds that observed
digest into `BridgeIdentity`; a different declared digest raises
`ImageDigestMismatchError`. Record a new fixture identity after every rebuild.
Build the `assay-pier-bridge:qualify-local` image once and set the paid runner's
`PIER_BRIDGE_IMAGE_DIGEST` pin to its inspected digest. `qualify_local.py`
inspects that existing image and reinspects it immediately before publishing
its inventory; it does not rebuild the image. The
workflow edit Node manifest and npm lockfile live in
`integrations/pier/workflow_edit/` so the bridge's Docker build context can
copy them directly. npm installs the complete locked tree during the build;
the final image carries Node and that tree, without npm.

Qualification commands:

```sh
docker build -t assay-pier-bridge:qualify-local integrations/pier
docker image inspect --format '{{.Id}}' assay-pier-bridge:qualify-local
uv sync --locked --extra review --extra legacy
uv run ruff check integrations/pier
MYPYPATH=integrations/pier/src:experiments uv run mypy integrations/pier/scripts/qualify_local.py

cd integrations/pier
uv sync --locked --group dev
uv run mypy src
uv run pytest -q
```

`integrations/pier/scripts/qualify_local.py` validates the pinned bridge
identity, local container controls, guarded routing, artifact round trips,
accounting, and cancellation cleanup without a credential or network call.
It writes a `QualificationInventory` only after every probe passes.

The experiment runner, profiles, paid gates, bundle verification, recovery,
and rehearsal instructions now live in the
[`pier_qualification` README](../experiments/pier_qualification/README.md).
