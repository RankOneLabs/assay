"""Task K1: use the agent's native compaction summary as the session handoff (kbbl, at `1495ec34`).

kbbl's `core/` becomes the fixture's `src/` (`kbbl/core/acp/client.ts` lands at
`src/acp/client.ts`), so every relative import inside the slice is unchanged. Colocated
pinned tests move to `tests/visible/`, and the one that reveals the projector edit moves to
the hidden regression group. Nothing outside `kbbl/core/` is reached, so the default
writable scope `src/` covers every edit.
"""
# ruff: noqa: E501 - embedded TypeScript keeps the fixture's own line lengths.

from __future__ import annotations

from code_extension.library import HIDDEN_MOVE, RELOCATION, Edit, LibraryTask, Patches, Requirements
from code_extension.slice import Replacement, SliceSpec

_CORE = "kbbl/core/"
_SOURCES = (
    "acp/agent-profile.ts",
    "acp/client.ts",
    "acp/controller-registry.ts",
    "acp/controller.ts",
    "acp/default-profiles.ts",
    "acp/event-projector.ts",
    "acp/process-supervisor.ts",
    "acp/resume-context.ts",
    "acp/session-service.ts",
    "acp/session-summary.ts",
    "acp/store.ts",
    "acp/types.ts",
    "config.ts",
    "db/migrations.ts",
    "db/migrations/001_sessions.sql",
    "db/migrations/002_session_archive.sql",
    "db/migrations/003_gated_review.sql",
    "db/test-db.ts",
    "pwa/oakridge/operator-contracts.ts",
    "runtime.ts",
    "session/serialize-by-key.ts",
    "session/worktree.ts",
)
# pinned test -> (relative "./" imports, relative "../" imports)
_VISIBLE_TESTS = {
    "client.test.ts": (1, 0),
    "resume-context.test.ts": (2, 0),
    "session-summary.test.ts": (2, 0),
    "store.test.ts": (2, 1),
}
# Moved to the hidden group: it asserts that a compaction update projects to null, which
# points straight at the projector edit (survey decision 3).
_TRANSFORMS_HIDDEN = "hidden/regression/tests/hidden/regression/transforms.test.ts"
_PINNED_UNKNOWN = (
    '      sessionUpdate: "compaction_update",\n'
    '      compactionId: "c1",\n'
    '      status: "in_progress",\n'
)
_AUTHORED_UNKNOWN = '      sessionUpdate: "an_unknown_extension_update",\n'

NATIVE_COMPACTION_SUMMARY = SliceSpec(
    package_name="oakridge-kbbl-native-compaction-summary",
    files={
        **{f"{_CORE}{path}": f"src/{path}" for path in _SOURCES},
        **{f"{_CORE}acp/{name}": f"tests/visible/{name}" for name in _VISIBLE_TESTS},
        f"{_CORE}acp/transforms.test.ts": _TRANSFORMS_HIDDEN,
    },
    replacements=(
        # "../" first: the "./" rewrite after it writes new "../" text.
        *(
            Replacement(f"tests/visible/{name}", '"../', '"../../src/', up)
            for name, (_, up) in _VISIBLE_TESTS.items() if up
        ),
        *(
            Replacement(f"tests/visible/{name}", '"./', '"../../src/acp/', here)
            for name, (here, _) in _VISIBLE_TESTS.items()
        ),
        Replacement(_TRANSFORMS_HIDDEN, '"./', '"../../../src/acp/', 4),
        # The pinned case used a compaction update as its unknown update; the feature gives
        # that update a projection, so the regression keeps the null case with a truly
        # unknown update type.
        Replacement(_TRANSFORMS_HIDDEN, _PINNED_UNKNOWN, _AUTHORED_UNKNOWN),
    ),
    typecheck_include=("src/**/*.ts", "tests/**/*.ts"),
)

_ACP = "src/acp/"

_CAPABILITY: Edit = (
    f"{_ACP}client.ts",
    "          clientCapabilities: {},\n",
    "          // ACP agents send compaction updates only to a client that\n"
    "          // advertises them; `{}` takes the complete compaction contract.\n"
    "          clientCapabilities: { session: { compaction: {} } },\n",
)
_EVENT_TYPES: Edit = (
    f"{_ACP}types.ts",
    '  | {\n      kind: "turn_state";',
    "  /**\n"
    "   * A context compaction the agent completed. `summary` is the retained\n"
    "   * summary the completed update carried, or null when it carried none.\n"
    "   */\n"
    '  | { kind: "compaction"; compactionId: string; summary: UiContent[] | null }\n'
    "  /** One streamed piece of a compaction's summary. */\n"
    '  | { kind: "compaction_chunk"; compactionId: string; content: UiContent[] }\n'
    '  | {\n      kind: "turn_state";',
)
_PROJECTOR_COMMENT: Edit = (
    f"{_ACP}event-projector.ts",
    " * the UI does not render (compaction internals, mode echoes, unknown\n",
    " * the UI does not render (unfinished compactions, mode echoes, unknown\n",
)


def _projector(completed_only: bool = True) -> Edit:
    statuses = (
        "      // Only a completed compaction retains a summary (ACP: a non-empty\n"
        "      // summary is valid only with `completed`).\n"
        '      if (update.status !== "completed") return null;\n'
    ) if completed_only else ""
    return (
        f"{_ACP}event-projector.ts",
        "    default:\n      return null;\n",
        '    case "compaction_summary_chunk":\n'
        "      return {\n"
        '        kind: "compaction_chunk",\n'
        "        compactionId: update.compactionId,\n"
        "        content: [contentBlockText(update.content)],\n"
        "      };\n"
        '    case "compaction_update":\n'
        f"{statuses}"
        "      return {\n"
        '        kind: "compaction",\n'
        "        compactionId: update.compactionId,\n"
        "        summary: update.summary == null ? null : update.summary.map(contentBlockText),\n"
        "      };\n"
        "    default:\n      return null;\n",
    )


_OWN_CHUNKS = 'event.kind === "compaction_chunk" && event.compactionId === completed.compactionId'


def _generator(chunk_filter: str = _OWN_CHUNKS) -> Edit:
    return (
        f"{_ACP}session-summary.ts",
        "/**\n * Explicit manual-compaction adapter.",
        "/**\n"
        " * The agent's own context compaction (ACP `compaction_update`). The latest\n"
        " * compaction completed in the final turn is the handoff: the summary on its\n"
        " * completed update is authoritative, and without one its own streamed\n"
        " * chunks are. Unfinished or failed compactions never count.\n"
        " */\n"
        "export class NativeCompactionSummaryGenerator implements SessionSummaryGenerator {\n"
        '  readonly method = "native_compaction" as const;\n'
        "\n"
        "  async generate(request: SessionSummaryRequest): Promise<Result<TerminalSessionSummaryDraft, SessionSummaryFailure>> {\n"
        "    const finalTurn = request.events.slice(\n"
        '      request.events.reduce((found, event, index) => event.kind === "user_message" ? index : found, -1) + 1,\n'
        "    );\n"
        "    const completed = [...finalTurn].reverse().find(\n"
        '      (event): event is Extract<AcpUiEvent, { kind: "compaction" }> => event.kind === "compaction",\n'
        "    );\n"
        "    if (!completed) {\n"
        '      return { ok: false, error: summaryFailure(this.method, request.session_id, "the final turn completed no compaction") };\n'
        "    }\n"
        "    const content = completed.summary !== null && completed.summary.length > 0\n"
        "      ? completed.summary\n"
        "      : finalTurn\n"
        '        .filter((event): event is Extract<AcpUiEvent, { kind: "compaction_chunk" }> =>\n'
        f"          {chunk_filter})\n"
        "        .flatMap((event) => event.content);\n"
        '    const markdown = content.map((part) => part.text).join("").trim();\n'
        "    if (!markdown) {\n"
        '      return { ok: false, error: summaryFailure(this.method, request.session_id, "the completed compaction retained no summary") };\n'
        "    }\n"
        "    return {\n"
        "      ok: true,\n"
        "      value: {\n"
        "        schema_version: 1,\n"
        "        session_id: request.session_id,\n"
        "        method: this.method,\n"
        "        produced_at: request.produced_at,\n"
        "        markdown,\n"
        "      },\n"
        "    };\n"
        "  }\n"
        "}\n"
        "\n"
        "/**\n * Explicit manual-compaction adapter.",
    )


_IMPORT: Edit = (
    f"{_ACP}session-service.ts",
    "  ManualCompactionSummaryGenerator,\n  type SessionSummaryGenerator,\n",
    "  ManualCompactionSummaryGenerator,\n  NativeCompactionSummaryGenerator,\n  type SessionSummaryGenerator,\n",
)
_DEFAULTS_OLD = (
    "    this.summaryGenerators = deps.summary_generators ?? [\n"
    "      new ManualCompactionSummaryGenerator(),\n"
    "      new FinalResponseSummaryGenerator(),\n"
    "    ];\n"
)


def _defaults(first: bool = True) -> Edit:
    native = "      new NativeCompactionSummaryGenerator(),\n"
    return (
        f"{_ACP}session-service.ts",
        _DEFAULTS_OLD,
        "    this.summaryGenerators = deps.summary_generators ?? [\n"
        + (native if first else "")
        + "      new ManualCompactionSummaryGenerator(),\n"
        "      new FinalResponseSummaryGenerator(),\n"
        + ("" if first else native)
        + "    ];\n",
    )


_FEATURE: tuple[Edit, ...] = (_EVENT_TYPES, _PROJECTOR_COMMENT, _projector(), _generator(), _IMPORT)

_PATCHES: Patches = {
    "reference.patch": (
        "Advertise compaction, project completed compactions and their chunks, and put a "
        "native-compaction generator first in the default strategy list.",
        (_CAPABILITY, *_FEATURE, _defaults()),
    ),
    "unreachable-capability.patch": (
        "Everything except the client capability, so a compliant agent never sends "
        "compaction updates.",
        (*_FEATURE, _defaults()),
    ),
    "unreachable-order.patch": (
        "The native generator is appended after the final-response fallback, which always "
        "answers first.",
        (_CAPABILITY, *_FEATURE, _defaults(first=False)),
    ),
    "wrong-chunks-across-ids.patch": (
        "Without a summary on the completed update, it concatenates the streamed chunks of "
        "every compaction in the turn, not just that compaction's.",
        (_CAPABILITY, _EVENT_TYPES, _PROJECTOR_COMMENT, _projector(),
         _generator('event.kind === "compaction_chunk"'), _IMPORT, _defaults()),
    ),
    "wrong-unfinished-compaction.patch": (
        "Every compaction update is projected as a compaction, so a failed or still "
        "running compaction's chunks become the handoff.",
        (_CAPABILITY, _EVENT_TYPES, _PROJECTOR_COMMENT, _projector(completed_only=False), _generator(), _IMPORT,
         _defaults()),
    ),
}

_REQUIREMENTS: Requirements = (
    ("A compliant agent's completed compaction becomes the session's terminal summary with "
     "method native_compaction.",
     ("native-summary-on-close", "stored-summary-text")),
    ("The native compaction summary takes priority over a manual /compact turn and over the "
     "final response.",
     ("native-before-manual",)),
    ("The summary carried on a completed compaction_update is authoritative and replaces its "
     "streamed chunks; when the completed update carries none, the handoff is the text of the "
     "compaction_summary_chunk updates for that same compactionId only.",
     ("summary-replaces-chunks", "chunks-of-own-compaction")),
    ("Failed, cancelled and unfinished compactions produce no native summary, and the next "
     "strategy runs.",
     ("failed-falls-through", "unfinished-falls-through")),
    ("Only the latest compaction completed in the final turn, after the last user message, "
     "counts.",
     ("latest-compaction-wins", "earlier-turn-is-stale")),
    ("A completed compaction whose trimmed text is empty produces no native summary, and the "
     "next strategy runs.",
     ("whitespace-summary-falls-through", "empty-compaction-falls-through")),
)

TASKS = (
    LibraryTask(
        scenario="native-compaction-summary",
        slice=NATIVE_COMPACTION_SUMMARY,
        patches=_PATCHES,
        requirements=_REQUIREMENTS,
        feature_tokens=("NativeCompactionSummaryGenerator",),
        local_adaptations=(
            RELOCATION,
            "kbbl's core/ directory becomes src/, so imports inside the slice are unchanged; "
            "its colocated tests move to tests/visible/.",
            HIDDEN_MOVE,
            "The moved projector test checks the null projection with an unknown update type "
            "instead of a compaction update, which the feature now projects.",
            "The new-behavior group ships its own fake ACP agent process, which sends "
            "compaction updates only to a client that advertised compaction.",
        ),
    ),
)
