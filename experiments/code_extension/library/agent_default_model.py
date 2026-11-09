"""Task: a per-agent default model and effort in kbbl's config (kbbl, at `1495ec34`).

kbbl's core moves from `kbbl/core/` to `src/`, so the agent works where the other library
tasks do. Its selected tests move to `tests/visible/` (flat), and the one monorepo neighbour
it reaches, `oakridge-dbos/src/...`, keeps its own path; the proxy handler's import of it
loses one `../`. The pinned fake ACP agent stays beside the test harness that launches it.
"""
# ruff: noqa: E501 - embedded TypeScript keeps the fixture's own line lengths.

from __future__ import annotations

from code_extension.library import HIDDEN_MOVE, RELOCATION, Edit, LibraryTask, Patches, Requirements
from code_extension.slice import Replacement, SliceSpec

_KBBL = "kbbl/core/"
_DBOS = "oakridge-dbos/src/"

_SOURCES = (
    "acp/__fixtures__/fake-acp-agent.ts",
    "acp/agent-profile.ts",
    "acp/client.ts",
    "acp/controller-registry.ts",
    "acp/controller.ts",
    "acp/event-projector.ts",
    "acp/process-supervisor.ts",
    "acp/pwa-session-order.ts",
    "acp/pwa-wire.ts",
    "acp/resumable-wire.ts",
    "acp/resume-context.ts",
    "acp/session-service.ts",
    "acp/session-summary.ts",
    "acp/store.ts",
    "acp/test-harness.ts",
    "acp/types.ts",
    "auth-wire.ts",
    "config.ts",
    "db/migrations.ts",
    "db/migrations/001_sessions.sql",
    "db/migrations/002_session_archive.sql",
    "db/migrations/003_gated_review.sql",
    "db/test-db.ts",
    "directories.ts",
    "live-stream.ts",
    "pwa/lib/result.ts",
    "pwa/oakridge/adapters/activity.ts",
    "pwa/oakridge/adapters/core.ts",
    "pwa/oakridge/adapters/gates.ts",
    "pwa/oakridge/adapters/parse.ts",
    "pwa/oakridge/artifact-types.ts",
    "pwa/oakridge/lib/pr-summary.ts",
    "pwa/oakridge/operator-contracts.ts",
    "pwa/oakridge/project-types.ts",
    "pwa/oakridge/repository-inputs.ts",
    "pwa/oakridge/run-types.ts",
    "runtime.ts",
    "server/app.ts",
    "server/auth.ts",
    "server/handlers/acp-inbox.ts",
    "server/handlers/acp-per-sid.ts",
    "server/handlers/directories.ts",
    "server/handlers/live-stream.ts",
    "server/handlers/oakridge-proxy.ts",
    "server/handlers/oakridge-read-cache.ts",
    "server/handlers/sessions.ts",
    "server/handlers/sse-backpressure.ts",
    "server/session-hold.ts",
    "session/serialize-by-key.ts",
    "session/session-hold.ts",
    "session/worktree.ts",
    "skills/fixtures.ts",
    "skills/format.ts",
    "skills/gated-review.ts",
    "skills/registry.ts",
    "skills/routes.ts",
    "skills/types.ts",
    "worktree/service.ts",
)
_DBOS_SOURCES = (
    "core-client/core-types.ts",
    "http/browser-write-policy.ts",
    "http/control-auth.ts",
    "http/errors.ts",
    "http/routes.ts",
)
# pinned test -> fixture path; each lands flat in tests/visible/
_VISIBLE = {
    "config.test.ts": "tests/visible/config.test.ts",
    "server/app.test.ts": "tests/visible/app.test.ts",
    "server/handlers/sessions.model.test.ts": "tests/visible/sessions.model.test.ts",
}
# Moved to the hidden group: its session-mode tests run the profile's start setting
# through ensureResumableSession, the second create path the task should make the agent find.
_SERVICE_HIDDEN = "hidden/regression/tests/hidden/regression/service.test.ts"
_UP = "../../src/"
_UP_HIDDEN = "../../../src/"

AGENT_DEFAULT_MODEL = SliceSpec(
    package_name="oakridge-kbbl-agent-default-model",
    files={
        **{f"{_KBBL}{path}": f"src/{path}" for path in _SOURCES},
        **{f"{_DBOS}{path}": f"{_DBOS}{path}" for path in _DBOS_SOURCES},
        **{f"{_KBBL}{path}": target for path, target in _VISIBLE.items()},
        f"{_KBBL}acp/service.test.ts": _SERVICE_HIDDEN,
    },
    replacements=(
        Replacement(
            "src/server/handlers/oakridge-proxy.ts", '"../../../../oakridge-dbos/', '"../../../oakridge-dbos/', 3,
        ),
        Replacement("tests/visible/config.test.ts", '"./config"', f'"{_UP}config"'),
        Replacement("tests/visible/app.test.ts", '"../', f'"{_UP}', 3),
        Replacement("tests/visible/app.test.ts", '"./', f'"{_UP}server/', 2),
        Replacement(
            "tests/visible/app.test.ts", '  test("rejects paths outside allowed roots", async () => {\n',
            "  // Skipped in the fixture: the evaluator's sandbox sets HOME=/tmp, an allowed root,\n"
            "  // so no temporary directory can lie outside the allowed roots there.\n"
            '  test.skip("rejects paths outside allowed roots", async () => {\n',
        ),
        Replacement("tests/visible/sessions.model.test.ts", '"./sessions"', f'"{_UP}server/handlers/sessions"'),
        Replacement("tests/visible/sessions.model.test.ts", '"../../acp/', f'"{_UP}acp/', 2),
        Replacement(_SERVICE_HIDDEN, '"../db/', f'"{_UP_HIDDEN}db/'),
        Replacement(_SERVICE_HIDDEN, 'from "./', f'from "{_UP_HIDDEN}acp/', 6),
        Replacement(
            _SERVICE_HIDDEN, 'join(import.meta.dir, "__fixtures__",',
            f'join(import.meta.dir, "{_UP_HIDDEN}acp/__fixtures__",',
        ),
    ),
    typecheck_include=("src/**/*.ts", "tests/**/*.ts", "oakridge-dbos/**/*.ts"),
)

_CONFIG: Edit = (
    "src/config.ts",
    "    session_mode: z.string().min(1).nullable().default(null),\n",
    "    session_mode: z.string().min(1).nullable().default(null),\n"
    "    // Model and effort a new session requests when its create or ensure\n"
    "    // request names none. Null leaves the agent's own default in place.\n"
    "    default_model: z.string().min(1).nullable().default(null),\n"
    "    default_effort: z.string().min(1).nullable().default(null),\n",
)
_PROFILE_TYPE: Edit = (
    "src/acp/agent-profile.ts",
    "  readonly sessionMode: string | null;\n",
    "  readonly sessionMode: string | null;\n"
    "  /**\n"
    "   * Model and effort a new session requests when its request names none.\n"
    "   * Absent or null leaves the agent's own default.\n"
    "   */\n"
    "  readonly defaultModel?: string | null;\n"
    "  readonly defaultEffort?: string | null;\n",
)
_PROFILE_LOAD: Edit = (
    "src/acp/agent-profile.ts",
    "      sessionMode: agent.session_mode,\n",
    "      sessionMode: agent.session_mode,\n"
    "      defaultModel: agent.default_model,\n"
    "      defaultEffort: agent.default_effort,\n",
)
_SERVICE_HELPER: Edit = (
    "src/acp/session-service.ts",
    "    return this.deps.profiles.get(profileId)?.sessionMode ?? null;\n  }\n",
    "    return this.deps.profiles.get(profileId)?.sessionMode ?? null;\n  }\n\n"
    "  /** The profile's default model and effort; null when the profile is unknown or sets none. */\n"
    "  private profileDefaults(profileId: AgentProfileId): { model: string | null; effort: string | null } {\n"
    "    const profile = this.deps.profiles.get(profileId);\n"
    "    return { model: profile?.defaultModel ?? null, effort: profile?.defaultEffort ?? null };\n"
    "  }\n",
)
_REQUESTED = (
    "      requested_model: spec.model ?? null,\n"
    "      requested_effort: spec.effort ?? null,\n"
    "      requested_mode: this.profileSessionMode(profileId),\n"
)
# What the request names wins; the profile's default fills only what it leaves unset.
_DEFAULTED = (
    "      requested_model: spec.model ?? this.profileDefaults(profileId).model,\n"
    "      requested_effort: spec.effort ?? this.profileDefaults(profileId).effort,\n"
    "      requested_mode: this.profileSessionMode(profileId),\n"
)
_OVERRIDING = (
    "      requested_model: this.profileDefaults(profileId).model ?? spec.model ?? null,\n"
    "      requested_effort: this.profileDefaults(profileId).effort ?? spec.effort ?? null,\n"
    "      requested_mode: this.profileSessionMode(profileId),\n"
)


def _ensure(requested: str) -> Edit:
    return ("src/acp/session-service.ts", _REQUESTED + "      workflow: identity,\n",
            requested + "      workflow: identity,\n")


def _create(requested: str) -> Edit:
    return ("src/acp/session-service.ts", _REQUESTED + "      workflow: null,\n",
            requested + "      workflow: null,\n")


_LIST_PROFILES: Edit = (
    "src/acp/session-service.ts",
    "  listProfiles(): Array<{ id: string; label: string; enabled: boolean }> {\n"
    "    return [...this.deps.profiles.values()].map((profile) => ({\n"
    "      id: profile.id,\n"
    "      label: profile.label,\n"
    "      enabled: profile.enabled,\n"
    "    }));\n",
    "  listProfiles(): Array<{\n"
    "    id: string;\n    label: string;\n    enabled: boolean;\n"
    "    defaultModel?: string;\n    defaultEffort?: string;\n  }> {\n"
    "    return [...this.deps.profiles.values()].map((profile) => ({\n"
    "      id: profile.id,\n"
    "      label: profile.label,\n"
    "      enabled: profile.enabled,\n"
    "      ...(profile.defaultModel ? { defaultModel: profile.defaultModel } : {}),\n"
    "      ...(profile.defaultEffort ? { defaultEffort: profile.defaultEffort } : {}),\n"
    "    }));\n",
)
_APP_CONFIG: Edit = (
    "src/server/app.ts",
    "        .map((profile) => {\n"
    "          if (!isRuntimeId(profile.id)) {\n"
    "            return {\n"
    "              id: profile.id,\n"
    "              label: profile.label,\n"
    "              models: [],\n"
    "              efforts: [],\n"
    "            };\n"
    "          }\n"
    "          return {\n"
    "            id: profile.id,\n"
    "            label: profile.label,\n"
    "            models: RUNTIME_MODELS[profile.id],\n"
    "            efforts: RUNTIME_EFFORTS[profile.id],\n"
    "          };\n",
    "        .map((profile) => {\n"
    "          // The launch form preselects a configured default; unset ones are omitted.\n"
    "          const defaults = {\n"
    "            ...(profile.defaultModel ? { defaultModel: profile.defaultModel } : {}),\n"
    "            ...(profile.defaultEffort ? { defaultEffort: profile.defaultEffort } : {}),\n"
    "          };\n"
    "          if (!isRuntimeId(profile.id)) {\n"
    "            return {\n"
    "              id: profile.id,\n"
    "              label: profile.label,\n"
    "              models: [],\n"
    "              efforts: [],\n"
    "              ...defaults,\n"
    "            };\n"
    "          }\n"
    "          return {\n"
    "            id: profile.id,\n"
    "            label: profile.label,\n"
    "            models: RUNTIME_MODELS[profile.id],\n"
    "            efforts: RUNTIME_EFFORTS[profile.id],\n"
    "            ...defaults,\n"
    "          };\n",
)
_SHARED = (_CONFIG, _PROFILE_TYPE, _PROFILE_LOAD, _SERVICE_HELPER, _LIST_PROFILES, _APP_CONFIG)

_PATCHES: Patches = {
    "reference.patch": (
        "Declare the defaults in config, carry them on the profile, fill them in on both create "
        "paths, and report them on /config.",
        (*_SHARED, _ensure(_DEFAULTED), _create(_DEFAULTED)),
    ),
    "unreachable-ensure.patch": (
        "The defaults are declared, loaded and reported, but only createSession applies them; "
        "the ensure path DBOS uses still requests nothing.",
        (*_SHARED, _create(_DEFAULTED)),
    ),
    "wrong-precedence.patch": (
        "The defaults reach both create paths but override a model or effort the request "
        "names or a resumed session inherits.",
        (*_SHARED, _ensure(_OVERRIDING), _create(_OVERRIDING)),
    ),
}

_REQUIREMENTS: Requirements = (
    ("An agent in config.acp.agents may declare default_model and default_effort; any new session "
     "for that agent whose request names no model (or effort) requests the default.",
     ("ensure-takes-defaults", "ensure-route-takes-defaults", "create-takes-defaults",
      "default-effort-alone", "default-survives-respawn")),
    ("A model or effort the request names, or that a resumed session inherits from its parent, "
     "wins over the default.",
     ("explicit-wins", "explicit-model-default-effort", "inherited-wins")),
    ("Defaults belong to the agent that declares them, and do not enter start_spec_hash.",
     ("defaults-per-agent", "defaults-not-hashed")),
    ("default_model and default_effort are optional non-empty strings; null or absent means none.",
     ("config-shape",)),
    ("GET /config reports an agent's defaults as defaultModel and defaultEffort on its runtimes "
     "entry, and omits each one the agent does not declare.",
     ("config-reports-defaults", "config-omits-unset")),
)

TASKS = (
    LibraryTask(
        scenario="agent-default-model",
        slice=AGENT_DEFAULT_MODEL,
        patches=_PATCHES,
        requirements=_REQUIREMENTS,
        feature_tokens=("default_model",),
        local_adaptations=(
            RELOCATION,
            "kbbl/core/ ships as src/ and its selected tests ship flat in tests/visible/; "
            "oakridge-dbos/src/ keeps its own path.",
            "One pinned /directories test is skipped: it needs a temporary directory outside "
            "HOME, and the evaluator's sandbox sets HOME=/tmp.",
            HIDDEN_MOVE,
        ),
    ),
)
