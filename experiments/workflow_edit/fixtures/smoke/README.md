# Throwaway qualification fixture

This fixture is pinned to oakridge-dbos commit
`f3b3ffca43e43672ff2f58ab797d65c7532aaed8`. Its study subject ID is
`oakridge-dbos-smoke-wf12`; `workflow_edit.shape.validate_worker_grid` rejects
that ID, so the fixture cannot enter a Part 2 worker grid.

The selected upstream source is `src/domain/artifact-types.ts`. The smoke
builder in `workflow_edit.smoke` adds a small Node test, package manifest, and
offline lockfile. The selected source is unchanged. The manifest binds the
observed local smoke image ID, which was built from the Pier bridge image with
npm copied from `node:lts-slim`; it must be rebound after any rebuild.

Two candidate slices were inventoried at the pinned commit:

| Candidate | Upstream source bytes | Result |
| --- | ---: | --- |
| `artifact-types.ts` | 3,661 | Selected; standalone typecheck and executable registry test |
| `json-pointer.ts` + `primitives.ts` | 5,006 | Larger; no smaller benefit for this footprint probe |

The selected model-visible snapshot has 4 files and 6,763 UTF-8 bytes,
leaving 196 files and 993,237 bytes under the current Pier packaging defaults
of 200 files and 1,000,000 bytes. `validate_repository` checks every path and
the count/byte limits before materialization. These are the Pier default
limits; no workflow-edit arm worker configuration with explicit repository
limits exists in this checkout.

The offline trial used `npm ci --offline` against the image's local TypeScript
package, `tsc --noEmit --strict`, compilation, and `node --test`. It exited
successfully under Docker's `none` network mode. The required hidden-test,
patch, and rubric digest fields in `MANIFEST.json` are smoke-only placeholders;
this manifest must not be used as a study fixture.

The later non-root model-loop qualification used `npm ci --offline
--no-bin-links`: npm otherwise tried to chmod the linked TypeScript binary
on the image's read-only root. All 20 measured cells installed, typechecked,
and tested successfully with that flag. `RepositoryAgentClient` ran with
`qualify_smoke=True`, which records four harness-controlled checks before each
model request; every cell then made two local Smithers requests with a tool
result between them. The image was not rebuilt, so its observed digest above
remains bound.

From the Assay checkout, reproduce the first two gates with:

```sh
PYTHONPATH=experiments uv run python experiments/workflow_edit/smoke.py prepare /home/steve/codes/rol/oakridge .wf12-fixture
PYTHONPATH=experiments uv run python experiments/workflow_edit/smoke.py build-image
PYTHONPATH=experiments uv run python experiments/workflow_edit/smoke.py trial .wf12-fixture --inspect-output .wf12-inspect.json
uv run --project integrations/pier python integrations/pier/scripts/qualify_local.py --smoke-container assay-wf12-smoke-observed --smoke-fixture-dir .wf12-fixture --image-tag assay-wf12-smoke:local
```

The trial command requires a fresh container name and prints the test log.
The binding command requires the exact directory mounted at `/work` in that
container and returns its sealed artifacts for publication. `smoke.publish`
checks those artifacts against the live Docker inspection and package snapshot.
The bound image digest in `MANIFEST.json` must match the rebuilt image before
its measurements are used.
