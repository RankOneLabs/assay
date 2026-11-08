# Gated-review shortcuts

Subject `oakridge-kbbl-gated-review-shortcuts` offers the skills rail's gated-review MCP
shortcuts only to the kbbl sessions whose agent is given the gated-review server. It is
survey item K3, cut from oakridge `1495ec34`. Its shape is the code's own: a policy that
already exists in `acp/client.ts` (`selectGatedReviewAccess` and `selectMcpServers`, used
when kbbl attaches the server to the agent) has to be applied in `skills/`, at two
boundaries. The listing route is the obvious one. The invoke route re-aggregates the
skill list on its own, and it is the authorization boundary, so a filter applied only to
the listing still lets a crafted id dispatch.

## Provenance

Cut by `uv run python -m code_extension.slice --scenario gated-review-shortcuts --oakridge
<oakridge>` from oakridge commit `1495ec34`. The slice spec in
`code_extension/library/gated_review_shortcuts.py` lists every pinned file and every edit
made while moving it.

| Fixture path | Source at the pin | Why included |
| --- | --- | --- |
| `src/**` | `kbbl/core/**`, the import closure of the skills routes, the test service and the fake agent | The code the feature passes through, and the service the routes run over |
| `src/db/migrations/*.sql` | `kbbl/core/db/migrations/` | Read at runtime by the in-memory test database |
| `src/acp/test-harness.ts`, `src/acp/__fixtures__/fake-acp-agent.ts` | same paths under `kbbl/core/` | The pinned test service and the fake agent process it spawns; both already exist in kbbl |
| `tests/visible/{skills,gated-review}.test.ts` | `kbbl/core/skills/` | Public checks |
| `package.json`, `package-lock.json` | `integrations/pier/scenario_library/` | The image's dependency lock, renamed; versions match oakridge's `bun.lock` |
| `tsconfig.json` | authored | The pinned compiler options, flattened |

The repository has 36 files and 284,178 bytes, under the 200-file and 1,000,000-byte limits.

## Edits made while moving files

- kbbl's server code moves from `kbbl/core/` to `src/` as a whole, so no source import
  changes, and the default writable scope `src/` covers the edit.
- The two shipped tests move from beside their modules to `tests/visible/`, so `./` becomes
  `../../src/skills/` and `../` becomes `../../src/`.
- The hidden regression test moves to `tests/hidden/regression/`, so `./client` becomes
  `../../../src/acp/client`.

No production behavior is changed. No test helper is replaced: the tests use kbbl's own
in-memory SQLite database and fake agent process, with no network.

## Hidden groups

- **Regression:** `client.test.ts`, the pinned tests of `selectGatedReviewAccess` and
  `selectMcpServers`. It moved out of the visible tests because it names the policy the task
  should make the agent find and reuse.
- **New behavior:** `gated-review-shortcuts.test.ts`. It runs the real skills routes over
  `makeAcpTestService`, with sessions created by hand and ensured with workflow identities
  with and without a grant, and sets and restores `OAKRIDGE_GATED_REVIEW_URL` around each
  test. Titles start with `reachability:` when the test fails unless the listing route
  applies the filter, and `semantics:` otherwise.

## Patches

| Patch | What it does | Should fail |
| --- | --- | --- |
| `reference.patch` | Applies the attachment policy to the session's skills at listing and invoke | nothing |
| `unreachable-helper.patch` | The filtered skills exist in a helper that no route calls | reachability (and the invoke refusals) |
| `wrong-invoke-unfiltered.patch` | Listing filtered, invoke not, so a crafted id still dispatches | semantics only |
| `wrong-skips-url.patch` | Both routes filter by the grant alone, ignoring an unset URL | semantics only |
