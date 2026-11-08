"""Task K2: show each session's context-window usage in the inbox (kbbl, at `1495ec34`).

kbbl keeps its server code under `kbbl/core/`, with tests beside the code. The slice moves
`kbbl/core/` to `src/` as one block, so every import inside it is unchanged and the default
writable scope `src/` covers the migrations directory (`src/db/migrations/`). Shipped tests
move to `tests/visible/` (flat) and the controller-path service test to the hidden
regression group, with their relative imports rewritten.
"""
# ruff: noqa: E501 - embedded TypeScript keeps the fixture's own line lengths.

from __future__ import annotations

from code_extension.library import HIDDEN_MOVE, Edit, LibraryTask, Patches, Requirements
from code_extension.slice import Replacement, SliceSpec

_CORE = "kbbl/core/"

_USAGE_SOURCES = (
    "acp/__fixtures__/fake-acp-agent.ts",
    "acp/agent-profile.ts",
    "acp/client.ts",
    "acp/controller-registry.ts",
    "acp/controller.ts",
    "acp/event-projector.ts",
    "acp/process-supervisor.ts",
    "acp/pwa-session-order.ts",
    "acp/pwa-wire.ts",
    "acp/session-service.ts",
    "acp/session-summary.ts",
    "acp/store.ts",
    "acp/test-harness.ts",
    "acp/types.ts",
    "config.ts",
    "db/migrations.ts",
    "db/migrations/001_sessions.sql",
    "db/migrations/002_session_archive.sql",
    "db/migrations/003_gated_review.sql",
    "db/test-db.ts",
    "pwa/oakridge/operator-contracts.ts",
    "runtime.ts",
    "server/handlers/acp-inbox.ts",
    "server/handlers/sse-backpressure.ts",
    "session/serialize-by-key.ts",
    "session/worktree.ts",
    "worktree/service.ts",
)
# pinned test -> (fixture path, [(old import, new import)])
_USAGE_TESTS = {
    "acp/store.test.ts": ("tests/visible/store.test.ts", (
        ('"../db/test-db"', '"../../src/db/test-db"'),
        ('"./store"', '"../../src/acp/store"'),
        ('"./types"', '"../../src/acp/types"'),
    )),
    "server/handlers/acp-inbox.test.ts": ("tests/visible/acp-inbox.test.ts", (
        ('"../../acp/test-harness"', '"../../src/acp/test-harness"'),
        ('"../../acp/pwa-wire"', '"../../src/acp/pwa-wire"'),
        ('"./acp-inbox"', '"../../src/server/handlers/acp-inbox"'),
    )),
    "db/migrations.test.ts": ("tests/visible/migrations.test.ts", (
        ('"./migrations"', '"../../src/db/migrations"'),
        ('"./test-db"', '"../../src/db/test-db"'),
    )),
}
# Moved to the hidden group: it drives the controller through the service, and its
# replay test shows how `handleUpdate` keeps session/load history from writing the store,
# which is the non-local edit the task should make the agent find.
_USAGE_HIDDEN = "hidden/regression/tests/hidden/regression/service.test.ts"

CONTEXT_USAGE_INBOX = SliceSpec(
    package_name="oakridge-kbbl-context-usage-inbox",
    files={
        **{f"{_CORE}{path}": f"src/{path}" for path in _USAGE_SOURCES},
        **{f"{_CORE}{pinned}": target for pinned, (target, _) in _USAGE_TESTS.items()},
        f"{_CORE}acp/service.test.ts": _USAGE_HIDDEN,
    },
    replacements=(
        *(
            Replacement(target, old, new)
            for target, edits in _USAGE_TESTS.values() for old, new in edits
        ),
        Replacement(_USAGE_HIDDEN, '"../db/test-db"', '"../../../src/db/test-db"'),
        Replacement(_USAGE_HIDDEN, '"./', '"../../../src/acp/', 6),
        Replacement(
            _USAGE_HIDDEN, 'join(import.meta.dir, "__fixtures__", "fake-acp-agent.ts")',
            'join(import.meta.dir, "../../../src/acp/__fixtures__", "fake-acp-agent.ts")',
        ),
    ),
    typecheck_include=("src/**/*.ts", "tests/**/*.ts"),
)

_MIGRATION: Edit = (
    "src/db/migrations/004_context_usage.sql",
    "",
    "-- The agent's latest live context-window report (ACP usage_update), in tokens.\n"
    "-- Null until the session's first live report.\n"
    "ALTER TABLE acp_sessions ADD COLUMN context_used INTEGER;\n"
    "ALTER TABLE acp_sessions ADD COLUMN context_size INTEGER;\n",
)
_ROW_TYPE: Edit = (
    "src/acp/types.ts",
    "  updated_at: string;\n  workflow: AcpSessionWorkflowIdentity | null;\n}",
    "  updated_at: string;\n  workflow: AcpSessionWorkflowIdentity | null;\n"
    "  /** Tokens in the agent's context at its latest live usage_update; null until one. */\n"
    "  context_used: number | null;\n"
    "  /** The agent's context window in tokens at that update; null until one. */\n"
    "  context_size: number | null;\n}",
)
_SNAPSHOT_TYPE: Edit = (
    "src/acp/types.ts",
    "  last_activity_at: string;\n  created_at: string;\n  workflow: AcpSessionWorkflowIdentity | null;\n}",
    "  last_activity_at: string;\n  created_at: string;\n  workflow: AcpSessionWorkflowIdentity | null;\n"
    "  context_used: number | null;\n  context_size: number | null;\n}",
)
_RAW_ROW: Edit = (
    "src/acp/store.ts",
    "  gated_review_json: string | null;\n}",
    "  gated_review_json: string | null;\n  context_used: number | null;\n  context_size: number | null;\n}",
)
_SETTER_ANCHOR = "  setAcpSessionId(sid: KbblSessionId, acpSessionId: string): void {\n"


def _setter(first: str, second: str) -> Edit:
    return (
        "src/acp/store.ts",
        _SETTER_ANCHOR,
        "  /** Latest live context-window usage, in tokens; every report overwrites the last. */\n"
        "  setContextUsage(sid: KbblSessionId, used: number, size: number): void {\n"
        "    this.db\n"
        "      .prepare(\n"
        '        "UPDATE acp_sessions SET context_used = ?, context_size = ?, updated_at = ? WHERE sid = ?",\n'
        "      )\n"
        f"      .run({first}, {second}, nowIso(), sid);\n"
        "    this.notifySessionsChanged();\n"
        "  }\n\n" + _SETTER_ANCHOR,
    )


_TO_SNAPSHOT: Edit = (
    "src/acp/store.ts",
    "    created_at: row.created_at,\n    workflow: row.workflow,\n  };",
    "    created_at: row.created_at,\n    workflow: row.workflow,\n"
    "    context_used: row.context_used,\n    context_size: row.context_size,\n  };",
)
_WIRE: tuple[Edit, ...] = (
    ("src/acp/pwa-wire.ts",
     "  pendingPermissionCount: number;\n  workflow: PwaSessionWorkflowIdentity | null;\n}",
     "  pendingPermissionCount: number;\n  workflow: PwaSessionWorkflowIdentity | null;\n"
     "  /** Tokens in the agent's context at its latest live report; null until one. */\n"
     "  contextUsed: number | null;\n"
     "  /** The agent's context window in tokens; null until a report. */\n"
     "  contextSize: number | null;\n}"),
    ("src/acp/pwa-wire.ts",
     "    workflow: toPwaWorkflowIdentity(snapshot.workflow),\n  };",
     "    workflow: toPwaWorkflowIdentity(snapshot.workflow),\n"
     "    contextUsed: snapshot.context_used,\n    contextSize: snapshot.context_size,\n  };"),
)
_STORED: tuple[Edit, ...] = (_MIGRATION, _ROW_TYPE, _SNAPSHOT_TYPE, _RAW_ROW, _TO_SNAPSHOT, *_WIRE)
_HANDLE_ANCHOR = "    if (!this.replaying) this.deps.store.touchActivity(this.deps.sid);\n"


def _controller(guard: str) -> Edit:
    return (
        "src/acp/controller.ts",
        _HANDLE_ANCHOR,
        _HANDLE_ANCHOR
        + "    // Replayed history is not the agent's current context: only a live report counts.\n"
        + f'    if ({guard}notification.update.sessionUpdate === "usage_update") {{\n'
        + "      const { used, size } = notification.update;\n"
        + "      this.deps.store.setContextUsage(this.deps.sid, used, size);\n"
        + "    }\n",
    )


_USAGE_PATCHES: Patches = {
    "reference.patch": (
        "Persist each live usage_update and expose it on the snapshot and the browser wire.",
        (*_STORED, _setter("used", "size"), _controller("!this.replaying && ")),
    ),
    "unreachable-controller.patch": (
        "The column, setter, snapshot and wire fields exist, but the controller never calls the setter.",
        (*_STORED, _setter("used", "size")),
    ),
    "wrong-replay.patch": (
        "Usage is stored, but updates replayed by session/load overwrite the live value.",
        (*_STORED, _setter("used", "size"), _controller("")),
    ),
    "swapped-fields.patch": (
        "Usage is stored on live updates only, but used and size land in each other's fields.",
        (*_STORED, _setter("size", "used"), _controller("!this.replaying && ")),
    ),
}

_USAGE_REQUIREMENTS: Requirements = (
    ("Each live ACP usage_update an agent sends is persisted on its session: the session "
     "snapshot carries context_used and context_size, and the browser wire (session list and "
     "/inbox frames) carries contextUsed and contextSize, all in tokens.",
     ("usage-reaches-snapshot", "usage-reaches-inbox", "usage-survives-restart")),
    ("context_used/contextUsed is the update's used and context_size/contextSize is its size.",
     ("used-and-size-fields", "wire-fields")),
    ("Every live update overwrites the stored value, including one that lowers it; there is "
     "no throttling.", ("latest-update-wins",)),
    ("Updates replayed while kbbl loads a session's history do not change the stored value.",
     ("replay-keeps-live-value",)),
    ("A session that has had no live usage update reports null in all four fields.",
     ("unset-is-null",)),
)


TASKS = (
    LibraryTask(
        scenario="context-usage-inbox",
        slice=CONTEXT_USAGE_INBOX,
        patches=_USAGE_PATCHES,
        requirements=_USAGE_REQUIREMENTS,
        feature_tokens=("context_used",),
        local_adaptations=(
            "kbbl/core/ moves to src/ as one block, so imports inside it are unchanged; tests "
            "move out of the source tree and only their relative import paths change. The "
            "slice spec lists every edit.",
            HIDDEN_MOVE,
            "The hidden feature checks bring their own fake ACP agent, which reports "
            "usage_update; it ships only with the hidden group.",
        ),
    ),
)
