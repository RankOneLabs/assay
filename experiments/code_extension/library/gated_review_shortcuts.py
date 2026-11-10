"""Task K3: offer gated-review shortcuts only to sessions that get the server (kbbl, at `1495ec34`).

kbbl's server code moves from `kbbl/core/` to `src/`, so every relative import inside it
is unchanged and the default writable scope (`src/`) covers the edit. The shipped pinned
tests move from beside their modules to `tests/visible/`, and the pinned test of the
attachment policy moves to the hidden regression group.
"""
# ruff: noqa: E501 - embedded TypeScript keeps the fixture's own line lengths.

from __future__ import annotations

from code_extension.library import HIDDEN_MOVE, RELOCATION, Edit, LibraryTask, Patches, Requirements
from code_extension.slice import Replacement, SliceSpec

_CORE = "kbbl/core/"

_SOURCES = (
    "acp/__fixtures__/fake-acp-agent.ts",
    "acp/agent-profile.ts",
    "acp/client.ts",
    "acp/controller-registry.ts",
    "acp/controller.ts",
    "acp/event-projector.ts",
    "acp/process-supervisor.ts",
    "acp/session-service.ts",
    "acp/session-summary.ts",
    "acp/store.ts",
    "acp/test-harness.ts",
    "acp/types.ts",
    "config.ts",
    "db/migrations.ts",
    "db/test-db.ts",
    "pwa/oakridge/operator-contracts.ts",
    "runtime.ts",
    "server/handlers/acp-per-sid.ts",
    "server/handlers/sse-backpressure.ts",
    "session/serialize-by-key.ts",
    "session/worktree.ts",
    "skills/fixtures.ts",
    "skills/format.ts",
    "skills/gated-review.ts",
    "skills/registry.ts",
    "skills/routes.ts",
    "skills/types.ts",
    "worktree/service.ts",
)
_SKILLS_TEST = "tests/visible/skills.test.ts"
_CATALOG_TEST = "tests/visible/gated-review.test.ts"
# Moved to the hidden group: it is the test of the attachment policy in acp/client.ts,
# which points straight at the policy the task should make the agent find and reuse.
_POLICY_HIDDEN = "hidden/regression/tests/hidden/regression/client.test.ts"

GATED_REVIEW_SHORTCUTS = SliceSpec(
    package_name="oakridge-kbbl-gated-review-shortcuts",
    files={
        **{f"{_CORE}{path}": f"src/{path}" for path in _SOURCES},
        # Read at runtime by the in-memory test database, not imported.
        **{
            f"{_CORE}db/migrations/{name}": f"src/db/migrations/{name}"
            for name in ("001_sessions.sql", "002_session_archive.sql", "003_gated_review.sql")
        },
        f"{_CORE}skills/skills.test.ts": _SKILLS_TEST,
        f"{_CORE}skills/gated-review.test.ts": _CATALOG_TEST,
        f"{_CORE}acp/client.test.ts": _POLICY_HIDDEN,
    },
    replacements=(
        Replacement(_SKILLS_TEST, '"../', '"../../src/', 2),
        Replacement(_SKILLS_TEST, '"./', '"../../src/skills/', 6),
        Replacement(_CATALOG_TEST, '"./gated-review"', '"../../src/skills/gated-review"'),
        Replacement(_POLICY_HIDDEN, '"./client"', '"../../../src/acp/client"'),
    ),
)

_REGISTRY: Edit = (
    "src/skills/registry.ts",
    "export function aggregateSkillsForProfile(\n"
    "  profileId: string,\n"
    "  config: KbblConfig,\n"
    "): Skill[] {\n"
    "  const raw = config.skills.fixtures\n"
    "    ? FIXTURE_SKILLS.filter((skill) => skill.backend === profileId)\n"
    "    : gatedReviewSkills(profileId);\n",
    "export function aggregateSkillsForProfile(\n"
    "  profileId: string,\n"
    "  config: KbblConfig,\n"
    "  gatedReview = true,\n"
    "): Skill[] {\n"
    "  const raw = config.skills.fixtures\n"
    "    ? FIXTURE_SKILLS.filter((skill) => skill.backend === profileId)\n"
    "    : gatedReview ? gatedReviewSkills(profileId) : [];\n",
)
_IMPORTS: Edit = (
    "src/skills/routes.ts",
    'import type { AcpSessionService } from "../acp/session-service";\n',
    'import { selectGatedReviewAccess, selectMcpServers } from "../acp/client";\n'
    'import type { AcpSessionService } from "../acp/session-service";\n'
    'import type { AcpSessionSnapshot } from "../acp/types";\n',
)
_SKILL_TYPE_IMPORT: Edit = (
    "src/skills/routes.ts",
    'import { formatSkillInvocation } from "./format";\n',
    'import { formatSkillInvocation } from "./format";\nimport type { Skill } from "./types";\n',
)
_HELPER_ANCHOR = "export function mountSkillsRoutes(app: Hono, deps: SkillRoutesDeps): void {\n"


def _helper(attached: str) -> Edit:
    return (
        "src/skills/routes.ts",
        _HELPER_ANCHOR,
        "/**\n"
        " * The session's skills: the gated-review shortcuts only when the launcher\n"
        " * attaches the gated-review server to this session, by the same policy.\n"
        " */\n"
        "export function sessionSkills(session: AcpSessionSnapshot, config: KbblConfig): Skill[] {\n"
        f"  const attached = {attached};\n"
        "  return aggregateSkillsForProfile(session.agent_profile, config, attached);\n"
        "}\n\n" + _HELPER_ANCHOR,
    )


_POLICY = "selectMcpServers(process.env.OAKRIDGE_GATED_REVIEW_URL, selectGatedReviewAccess(session.workflow)).length > 0"
_LIST: Edit = (
    "src/skills/routes.ts",
    "return c.json(aggregateSkillsForProfile(session.agent_profile, config));",
    "return c.json(sessionSkills(session, config));",
)
_INVOKE: Edit = (
    "src/skills/routes.ts",
    "const skills = aggregateSkillsForProfile(session.agent_profile, config);",
    "const skills = sessionSkills(session, config);",
)
_GRANT_ONLY_IMPORTS: Edit = (
    "src/skills/routes.ts",
    'import type { AcpSessionService } from "../acp/session-service";\n',
    'import { selectGatedReviewAccess } from "../acp/client";\n'
    'import type { AcpSessionService } from "../acp/session-service";\n'
    'import type { AcpSessionSnapshot } from "../acp/types";\n',
)

_PATCHES: Patches = {
    "reference.patch": (
        "Apply the server-attachment policy to the session's skills at both listing and invoke.",
        (_REGISTRY, _IMPORTS, _SKILL_TYPE_IMPORT, _helper(_POLICY), _LIST, _INVOKE),
    ),
    "unreachable-helper.patch": (
        "The filtered session skills exist in a helper that no route calls.",
        (_REGISTRY, _IMPORTS, _SKILL_TYPE_IMPORT, _helper(_POLICY)),
    ),
    "unreachable-invoke.patch": (
        "The listing is filtered but invoke re-aggregates unfiltered, so a crafted id still dispatches.",
        (_REGISTRY, _IMPORTS, _SKILL_TYPE_IMPORT, _helper(_POLICY), _LIST),
    ),
    "wrong-skips-url.patch": (
        "Both routes are filtered by the grant alone, so shortcuts stay offered when no gated-review URL is configured.",
        (_REGISTRY, _GRANT_ONLY_IMPORTS, _SKILL_TYPE_IMPORT,
         _helper("selectGatedReviewAccess(session.workflow) !== null"), _LIST, _INVOKE),
    ),
}

_REQUIREMENTS: Requirements = (
    ("GET /sessions/:sid/skills lists the gated-review shortcuts only for a session that is given "
     "the gated-review server: OAKRIDGE_GATED_REVIEW_URL is set and the session's workflow "
     "identity carries a gated-review grant.",
     ("hand-started-lists-none", "ungranted-workflow-lists-none", "unset-url-lists-none",
      "granted-lists-all")),
    ("For any other session, a gated-review shortcut behaves as an unknown or hidden skill: "
     "invoking it answers 404 and submits nothing.",
     ("hand-started-invoke-refused", "ungranted-workflow-invoke-refused", "hidden-invoke-answers-404",
      "unset-url-invoke-refused", "granted-invoke-dispatches")),
    ("The decision depends only on whether a grant is present: every grant kind and role gets the "
     "same shortcuts.", ("every-grant-same-set",)),
    ("Fixture mode is unchanged: config.skills.fixtures still lists and invokes the fixture skills "
     "for every session.", ("fixture-mode-unchanged",)),
)


TASKS = (
    LibraryTask(
        scenario="gated-review-shortcuts",
        slice=GATED_REVIEW_SHORTCUTS,
        patches=_PATCHES,
        requirements=_REQUIREMENTS,
        feature_tokens=("OAKRIDGE_GATED_REVIEW_URL", "selectMcpServers", "selectGatedReviewAccess"),
        local_adaptations=(
            RELOCATION,
            "kbbl's server code moves from kbbl/core/ to src/ and its pinned tests from beside "
            "their modules to tests/visible/; no source import changes.",
            HIDDEN_MOVE,
        ),
    ),
)
