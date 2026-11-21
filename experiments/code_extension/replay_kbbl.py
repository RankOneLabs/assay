"""Build the kbbl Run-build replay fixture from two pinned Oakridge trees.

The replay starts from Oakridge 0f95ef0ea7 (PR #82 after round 1). Its task is
round 2 of that review, verbatim. The agent's own answer to it, 598956cb59,
showed a live build for any cohort with a non-null `current_session_ref`. The
server guard already skipped ended sessions; the client did not, and PR #99
fixed it. The fixture vendors kbbl/ plus the root configuration (not bun.lock).
It holds the reference (the agent's commit plus a port of #99), the agent's
commit as the main negative, a build-start-only-manual negative, and two
alternative correct fixes of different shapes.

Fetch both trees with `gh api repos/RankOneLabs/oakridge/tarball/<sha>` and
extract each with `--strip-components=1`, then run from experiments/:

    uv run python -m code_extension.replay_kbbl --start <0f95 tree> --agent <598956 tree>
"""

from __future__ import annotations

import argparse
import json
import posixpath
import re
import shutil
from collections.abc import Mapping
from pathlib import Path

from assay.canonical import canonical_json, digest_bytes
from assay.investigations.workflow_correctness import workflow_tree_digest
from assay.repository import validate_repository
from code_extension.authoring import unified_patch
from code_extension.fixture import COLOCATED_VISIBLE, PILOT, materialize, read_tree
from code_extension.fixtures import ExtensionScenarioSidecar, touched_paths

NAME = "kbbl-run-build-replay"
SUBJECT_ID = "oakridge-kbbl-run-build-replay"
START_SHA = "0f95ef0ea790ef014870bdbde74ea3111e200da6"
AGENT_SHA = "598956cb59e4eb21f70ad1e6b956cc13dc927a85"
FIX_SHA = "8c460e40033039f6d18531f0aeb039a680a77156"  # PR #99 merge
ROOT_FILES = ("package.json", "tsconfig.json", "README.md")
# The agent's commit also edited docs/known_issues.md, which the fixture does not carry.
AGENT_FILES = ("kbbl/core/pwa/review/brief/BriefReviewView.tsx", "kbbl/prompts/planner1.md")
COMMS = Path(__file__).resolve().parents[2] / "comms" / "oakridge-replay-pr99"
HIDDEN_TEST = "run-build-status.test.tsx"
# Visible tests a correct fix may need to edit: the #99 shape gives mountCohortsRoutes a
# required session manager, and these call it with { db }.
EDITABLE_TESTS = COLOCATED_VISIBLE[NAME].editable
REGRESSION_TESTS = (
    "kbbl/core/server/app.test.ts",
    "kbbl/core/db/briefs.test.ts",
    "kbbl/core/orchestrator/state-machine.test.ts",
    "kbbl/core/server/handlers/sessions.model.test.ts",
    "kbbl/core/server/handlers/sessions.task-binding.test.ts",
    "kbbl/core/orchestrator/backends/prompt-loader.test.ts",
)
# The harness's bun preflight bundles the tree's src/ modules; kbbl has no src/.
BUILD_ENTRY = "src/evaluator-build.ts"
BUILD_ENTRY_SOURCE = (
    "// Evaluator build entry for this replay; not part of kbbl. The evaluator bundles\n"
    "// src/ to check that the server and the review views still build.\n"
    'export { createApp } from "../kbbl/core/server/app";\n'
    'export { BriefReviewView } from "../kbbl/core/pwa/review/brief/BriefReviewView";\n'
)

Edit = tuple[str, str, str]

FIX_99: tuple[Edit, ...] = (
    (
        "kbbl/core/server/handlers/cohorts.ts",
        'import type { Cohort } from "../../types/task-tracker";\n',
        'import type { Cohort } from "../../types/task-tracker";\n'
        'import type { SessionManager } from "../../session/session-manager";\n',
    ),
    (
        "kbbl/core/server/handlers/cohorts.ts",
        "interface CohortsRouteDeps {\n  db: Database;\n}\n\n"
        "export function mountCohortsRoutes(app: Hono, deps: CohortsRouteDeps): void {\n"
        "  const { db } = deps;",
        "interface CohortsRouteDeps {\n  db: Database;\n  manager: SessionManager;\n}\n\n"
        "export function mountCohortsRoutes(app: Hono, deps: CohortsRouteDeps): void {\n"
        "  const { db, manager } = deps;",
    ),
    (
        "kbbl/core/server/handlers/cohorts.ts",
        '    if (!cohort) {\n      return c.json({ error: "not found" }, 404);\n    }\n'
        "    return c.json(cohort);\n  });",
        '    if (!cohort) {\n      return c.json({ error: "not found" }, 404);\n    }\n'
        "    // Resolve current_session_status from the live session manager so\n"
        "    // clients can distinguish a still-running session from a stale ref\n"
        "    // that the dispatcher never cleared. `null` means the session is no\n"
        "    // longer tracked (process restart, manual purge) and should be\n"
        "    // treated as ended for guard purposes — mirrors the server-side\n"
        "    // build guard in handlers/builds.ts.\n"
        "    const current_session_status = cohort.current_session_ref\n"
        "      ? (manager.get(cohort.current_session_ref)?.status ?? null)\n"
        "      : null;\n"
        "    return c.json({ ...cohort, current_session_status });\n  });",
    ),
    ("kbbl/core/server/app.ts", "  mountCohortsRoutes(app, { db });",
     "  mountCohortsRoutes(app, { db, manager });"),
    (
        "kbbl/core/pwa/review/brief/BriefReviewView.tsx",
        "      .then((r) => (r.ok ? (r.json() as Promise<{ current_session_ref: string | null }>)"
        " : null))",
        "      .then((r) =>\n        r.ok\n          ? (r.json() as Promise<{\n"
        "              current_session_ref: string | null;\n"
        "              current_session_status: string | null;\n            }>)\n"
        "          : null,\n      )",
    ),
    (
        "kbbl/core/pwa/review/brief/BriefReviewView.tsx",
        "        if (cohort?.current_session_ref) {",
        "        if (\n          cohort?.current_session_ref &&\n"
        "          cohort.current_session_status &&\n"
        '          cohort.current_session_status !== "ended"\n        ) {',
    ),
    *(
        (
            path,
            "  mountCohortsRoutes(app, { db });",
            "  mountCohortsRoutes(app, { db, manager: cohortsManager });",
        )
        for path in EDITABLE_TESTS
    ),
)
COHORTS_STUB = (
    "const cohortsManager = {\n  get: (_sid: string) => undefined,\n"
    '} as unknown as import("../session/session-manager").SessionManager;\n\n'
)

# Client only: resolve the ref against the existing GET /sessions list.
ALTERNATIVE_CLIENT: tuple[Edit, ...] = ((
    "kbbl/core/pwa/review/brief/BriefReviewView.tsx",
    "    fetch(`/cohorts/${encodeURIComponent(cohortId)}`)\n"
    "      .then((r) => (r.ok ? (r.json() as Promise<{ current_session_ref: string | null }>)"
    " : null))\n"
    "      .then((cohort) => {\n        if (cancelled) return;\n"
    "        if (cohort?.current_session_ref) {\n"
    "          setSessionRef(cohort.current_session_ref);\n        }\n      })",
    "    const liveRef = async (): Promise<string | null> => {\n"
    "      const r = await fetch(`/cohorts/${encodeURIComponent(cohortId)}`);\n"
    "      if (!r.ok) return null;\n"
    "      const cohort = (await r.json()) as { current_session_ref: string | null };\n"
    "      const ref = cohort.current_session_ref;\n      if (!ref) return null;\n"
    "      // The ref outlives its session; only a session still known and not\n"
    "      // ended is a running build (the same rule as the POST /build guard).\n"
    '      const list = await fetch("/sessions");\n      if (!list.ok) return null;\n'
    "      const { sessions } = (await list.json()) as "
    "{ sessions: { sid: string; status: string }[] };\n"
    "      const session = sessions.find((s) => s.sid === ref);\n"
    '      return session && session.status !== "ended" ? ref : null;\n    };\n'
    "    liveRef()\n      .then((ref) => {\n        if (cancelled) return;\n"
    "        if (ref) setSessionRef(ref);\n      })",
),)

# Server only: clear the cohort's ref when its session ends; the agent's client stays.
ALTERNATIVE_SERVER: tuple[Edit, ...] = ((
    "kbbl/core/server/app.ts",
    "  mountCohortsRoutes(app, { db });",
    "  mountCohortsRoutes(app, { db });\n"
    "  // A cohort's current_session_ref names a running session only while it runs:\n"
    "  // clear it when that session ends so readers never see a finished build.\n"
    "  manager.subscribeInbox?.((delta) => {\n"
    '    if (delta.type !== "session_ended") return;\n'
    '    db.prepare("UPDATE cohorts SET current_session_ref = NULL '
    'WHERE current_session_ref = ?")\n      .run(delta.sid);\n  });',
),)

# "Make build start exclusively manual", with the start tree's always-enabled button.
MANUAL_ONLY: tuple[Edit, ...] = (
    (
        "kbbl/core/orchestrator/dispatch-hooks.ts",
        '  const unsubBriefApproved = taskTrackerEvents.subscribe("brief.approved", '
        "({ brief_id }) => {\n"
        "    void (async () => {\n      try {\n"
        '        await dispatcher.dispatch("build", brief_id);\n',
        "  // Builds start only from the brief view's Run build button.\n"
        '  const unsubBriefApproved = taskTrackerEvents.subscribe("brief.approved", '
        "({ brief_id }) => {\n"
        "    void (async () => {\n      try {\n"
        "        void brief_id;\n",
    ),
)


def _apply(tree: Mapping[str, str], edits: tuple[Edit, ...]) -> dict[str, str]:
    result = dict(tree)
    for path, old, new in edits:
        count = result[path].count(old)
        if count != 1:
            raise ValueError(f"{path}: expected one match, found {count}: {old[:60]!r}")
        result[path] = result[path].replace(old, new)
    return result


def _with_cohort_stubs(tree: Mapping[str, str]) -> dict[str, str]:
    result = dict(tree)
    for path in EDITABLE_TESTS:
        source = result[path]
        last = source.rindex("\nimport ")
        cut = source.index("\n\n", last) + 2
        result[path] = source[:cut] + COHORTS_STUB + source[cut:]
    return result


def start_tree(source: Path) -> dict[str, str]:
    tree: dict[str, str] = {}
    for path in sorted((source / "kbbl").rglob("*")):
        if path.is_file():
            tree[path.relative_to(source).as_posix()] = path.read_text(encoding="utf-8")
    for name in ROOT_FILES:
        tree[name] = (source / name).read_text(encoding="utf-8")
    tree["tsconfig.json"] = adapt_tsconfig(tree["tsconfig.json"])
    tree[BUILD_ENTRY] = BUILD_ENTRY_SOURCE
    return validate_repository(tree)


def adapt_tsconfig(text: str) -> str:
    """The locked image has no vitest or vite, and owns the @types tree at /node_modules."""
    config = json.loads(text)
    options = config["compilerOptions"]
    options.pop("typeRoots")
    config["exclude"] = [
        *config["exclude"],
        "kbbl/core/pwa/**/*.test.ts",
        "kbbl/core/pwa/**/*.test.tsx",
        "kbbl/core/pwa/vite.config.ts",
        "kbbl/core/pwa/vitest.config.ts",
        "kbbl/core/pwa/vitest.setup.ts",
    ]
    return json.dumps(config, indent=2) + "\n"


_SPECIFIER = re.compile(r"""((?:from|import)\s*\(?\s*["'])(\.{1,2}/[^"']+)(["'])""")


def relocate(source: str, original: str, target: str) -> str:
    """Rewrite relative imports so a test moved from `original` to `target` still resolves."""

    def replace(match: re.Match[str]) -> str:
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(original), match[2]))
        moved = posixpath.relpath(resolved, posixpath.dirname(target))
        return match[1] + (moved if moved.startswith(".") else "./" + moved) + match[3]

    return _SPECIFIER.sub(replace, source)


def trees(start: Path, agent: Path) -> dict[str, dict[str, str]]:
    base = start_tree(start)
    mistake = dict(base)
    for path in AGENT_FILES:
        mistake[path] = (agent / path).read_text(encoding="utf-8")
    return {
        "start": base,
        "agent": mistake,
        "reference": _apply(_with_cohort_stubs(mistake), FIX_99),
        "alternative-client": _apply(mistake, ALTERNATIVE_CLIENT),
        "alternative-server": _apply(mistake, ALTERNATIVE_SERVER),
        "manual-only": _apply(base, MANUAL_ONLY),
    }


def hidden_files(start: Mapping[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    test = (COMMS / HIDDEN_TEST).read_text(encoding="utf-8").replace(
        '"../../../core/', '"../../../kbbl/core/'
    )
    new_behavior = {f"tests/hidden/new-behavior/{HIDDEN_TEST}": test}
    regression = {}
    for path in REGRESSION_TESTS:
        target = "tests/hidden/regression/" + path
        regression[target] = relocate(start[path], path, target)
    return regression, new_behavior


def write(destination: Path, start: Path, agent: Path) -> dict[str, object]:
    built = trees(start, agent)
    base = built["start"]
    root = destination / NAME
    for part in ("repository", "patches", "hidden"):
        if (root / part).exists():
            shutil.rmtree(root / part)
    materialize(root / "repository", base)
    if read_tree(root / "repository") != base:
        raise ValueError("materialized start tree differs")
    regression, new_behavior = hidden_files(base)
    materialize(root / "hidden" / "regression", regression)
    materialize(root / "hidden" / "new_behavior", new_behavior)
    (root / "patches").mkdir(parents=True)
    names = {
        "reference": "reference.patch",
        "agent": "negative.patch",
        "manual-only": "manual-only.patch",
        "alternative-client": "alternative-client.patch",
        "alternative-server": "alternative-server.patch",
    }
    patches = {}
    for label, name in names.items():
        patch = unified_patch(base, built[label])
        (root / "patches" / name).write_text(patch, encoding="utf-8")
        patches[name] = patch
    task = (COMMS / "task.md").read_text(encoding="utf-8")
    (root / "task.md").write_text(task, encoding="utf-8")
    (root / "README.md").write_text(README, encoding="utf-8")
    qualification = root / "qualification"
    qualification.mkdir(exist_ok=True)
    sidecar = _sidecar(base, patches)
    existing = qualification / "sidecar.json"
    if existing.is_file():
        # Qualification fills in the gate evidence; keep it across rebuilds.
        kept = ExtensionScenarioSidecar.model_validate_json(existing.read_bytes())
        sidecar = sidecar.model_copy(update={"evidence": kept.evidence})
    existing.write_bytes(canonical_json(sidecar.model_dump(mode="json")) + b"\n")
    return {
        "files": len(base),
        "bytes": sum(len(text.encode()) for text in base.values()),
        "tree_digest": workflow_tree_digest(base),
        "patches": {name: digest_bytes(patch.encode()) for name, patch in patches.items()},
        "visible_tests": len(COLOCATED_VISIBLE[NAME].select(base)),
        "regression_digest": digest_bytes(canonical_json(regression)),
    }


README = f"""# {NAME}

A replay of a real agent mistake in Oakridge, with one arm (`baseline`).

Do not publish this fixture content, including task text, hidden tests and solution
patches.

- Start tree: Oakridge {START_SHA} (PR #82 after review round 1), as kbbl/ plus the root
  package.json, tsconfig.json and README.md. bun.lock is left out; the image carries
  kbbl's locked dependencies (`integrations/pier/kbbl_replay/`).
- Task: round 2 of the PR #82 review, verbatim (one CodeRabbit and four Copilot
  comments), with one framing sentence.
- The agent's answer, {AGENT_SHA}, made the brief view treat any cohort with a
  `current_session_ref` as a live build, so Run build never came back once a build
  ended. The server guard already skipped ended sessions. PR #99 ({FIX_SHA}) fixed the
  client.

Held patches:
- reference.patch (reference): the agent's commit plus a port of #99. GET /cohorts/:id
  resolves the session status, and the view ignores ended sessions.
- negative.patch (incomplete): the agent's commit as written; the ended case fails.
- manual-only.patch (incomplete): build start made exclusively manual, with the button
  still always enabled; the live case fails.
- alternative-client.patch (reference): the agent's commit, with the view resolving the
  ref against the existing GET /sessions.
- alternative-server.patch (reference): the agent's commit, with the server clearing the
  ref when the session ends.

Grading:
- `new_behavior` runs `tests/hidden/new-behavior/{HIDDEN_TEST}` against the real
  app, session manager, build dispatcher and BriefReviewView in jsdom. While a build
  session is live, Run build must not be enabled. Once it has ended, Run build is
  enabled and starts a new build. A refresh while the view is open is not graded.
- `hidden_regression` runs six of kbbl's own test files, relocated:
  {", ".join(Path(path).name for path in REGRESSION_TESTS)}.
- `visible_regression` is kbbl's colocated bun suite (`COLOCATED_VISIBLE` in
  `code_extension/fixture.py`), restored before grading. It leaves out the PWA's vitest
  tests and the three tests a correct fix may need to edit
  ({", ".join(Path(path).name for path in EDITABLE_TESTS)}).

Adaptations:
- tsconfig.json drops `typeRoots`, because the image owns /node_modules/@types. It also
  excludes the PWA's vitest and vite files, because the image has neither.
- `{BUILD_ENTRY}` is added, because the evaluator's build check bundles `src/` and kbbl
  has none.

Generated by `python -m code_extension.replay_kbbl`; repository/, hidden/, patches/ and
this file are not edited by hand.
"""

LIVE = (
    "Either make build start exclusively manual, or have this UI display/refresh the existing "
    "automatic build session and only enable rerun after it has settled or completed."
)
EXISTING = "kbbl's existing server, database, orchestrator and session behavior is unchanged."


def _sidecar(base: Mapping[str, str], patches: Mapping[str, str]) -> ExtensionScenarioSidecar:
    intents = {
        "reference.patch": ("reference", "The agent's round-2 commit plus a port of PR #99."),
        "negative.patch": ("incomplete", "The agent's round-2 commit: ended builds still block."),
        "manual-only.patch": (
            "incomplete", "Build start made manual only; Run build stays enabled while live.",
        ),
        "alternative-client.patch": (
            "reference", "The agent's commit; the view checks the session via GET /sessions.",
        ),
        "alternative-server.patch": (
            "reference", "The agent's commit; the server clears the ref when the session ends.",
        ),
    }
    zero = "sha256:" + "0" * 64
    return ExtensionScenarioSidecar.model_validate({
        "subject_id": SUBJECT_ID,
        "writable_implementation_scope": ["docs/", "kbbl/"],
        "protected_assets": {
            "test_files": [],
            "dependency_files": ["package.json"],
            "configuration_files": ["tsconfig.json"],
        },
        "public_requirements": [LIVE],
        "preexisting_behaviors": [EXISTING],
        "test_assertions": [
            {"assertion_id": "live-build-blocks-rerun", "group_name": "new_behavior",
             "visibility": "hidden"},
            {"assertion_id": "ended-build-allows-rerun", "group_name": "new_behavior",
             "visibility": "hidden"},
            {"assertion_id": "kbbl-regressions", "group_name": "hidden_regression",
             "visibility": "hidden"},
            {"assertion_id": "kbbl-visible-suite", "group_name": "visible_regression",
             "visibility": "visible"},
        ],
        "requirements_to_tests": [
            {"assertion_id": "live-build-blocks-rerun", "citation_kind": "public_requirement",
             "citation": LIVE},
            {"assertion_id": "ended-build-allows-rerun", "citation_kind": "public_requirement",
             "citation": LIVE},
            {"assertion_id": "kbbl-regressions", "citation_kind": "preexisting_behavior",
             "citation": EXISTING},
        ],
        "patch_inventory": [
            {"arm_id": "baseline", "kind": intents[name][0],
             "digest": digest_bytes(patch.encode()), "intent": intents[name][1],
             "touched_paths": list(touched_paths(patch))}
            for name, patch in sorted(patches.items())
        ],
        "evidence": {key: zero for key in (
            "leak_scan", "access_probe", "no_op", "scripted_submission", "double_reproduction",
        )},
        "tool_instructions": (
            "Work within kbbl/ and docs/; keep the root package.json and tsconfig.json "
            "unchanged. Run kbbl's tests with bun test from the repository root and "
            "tsc --noEmit -p tsconfig.json, then submit with submit_output."
        ),
        "negative_expectations": [
            {"patch_name": "negative.patch", "intent": intents["negative.patch"][1],
             "intended_group": "new_behavior",
             "unrelated_results": {"visible_regression": "passed",
                                   "hidden_regression": "passed"}},
            {"patch_name": "manual-only.patch", "intent": intents["manual-only.patch"][1],
             "intended_group": "new_behavior",
             "unrelated_results": {"visible_regression": "passed",
                                   "hidden_regression": "passed"}},
        ],
        "provenance": {
            "extraction_invocation": (
                f"gh api repos/RankOneLabs/oakridge/tarball/{START_SHA} (and {AGENT_SHA}), "
                "each extracted with tar --strip-components=1; then uv run python -m "
                "code_extension.replay_kbbl --start <tree> --agent <tree>"
            ),
            "extraction_rules": [
                "Vendor kbbl/ and the root package.json, tsconfig.json and README.md "
                f"from {START_SHA}, unchanged; leave out bun.lock.",
                "Keep hidden checks, patches and qualification assets outside repository/.",
            ],
            "licenses": [
                "Oakridge is private source at the pinned commit; no license file is present.",
            ],
            "local_adaptations": [
                "tsconfig.json drops typeRoots and excludes the PWA's vitest and vite files.",
                f"{BUILD_ENTRY} is added as the evaluator's bun build entry.",
            ],
            "start_tree_digest": workflow_tree_digest(base),
            "start_file_count": len(base),
            "start_total_bytes": sum(len(text.encode()) for text in base.values()),
            "dependency_lock_digests": {},
        },
    })



def manifest_scope(
    subject_id: str, repository: Mapping[str, str]
) -> tuple[str, tuple[str, ...]] | None:
    """The replay's Oakridge pin and the vendored files that come from it, or None."""
    if subject_id != SUBJECT_ID:
        return None
    return START_SHA, tuple(sorted(path for path in repository if path != BUILD_ENTRY))

async def grade(image: str) -> dict[str, dict[str, object]]:
    """Grade the start tree and every held patch through the harness's Docker runner."""
    import re as regex

    from code_extension.fixtures import load_scenario
    from code_extension.qualify import make_runner, observed_image_digest

    fixture = load_scenario(NAME)
    runner = make_runner(observed_image_digest(image))
    results: dict[str, dict[str, object]] = {}
    root = PILOT.parent / NAME / "patches"
    for name in ("start", *sorted(path.name for path in root.glob("*.patch"))):
        patch = "" if name == "start" else (root / name).read_text(encoding="utf-8")
        expected = fixture.tree_digest
        if patch:
            import tempfile

            with tempfile.TemporaryDirectory() as directory:
                materialize(Path(directory), fixture.repository, patch)
                expected = workflow_tree_digest(read_tree(Path(directory)))
        result = await runner.run(
            baseline=fixture.repository,
            baseline_tree_digest=fixture.tree_digest,
            expected_tree_digest=expected,
            patch=patch,
            groups=fixture.groups,
            writable_scope=fixture.sidecar.writable_implementation_scope,
        )
        behavior = next(group for group in result.groups if group.name == "new_behavior")
        results[name] = {
            "verdict": result.verdict,
            "cause": result.cause,
            "groups": {group.name: group.status for group in result.groups},
            "new_behavior_tests": regex.findall(
                r"^\((pass|fail)\) .*? > (.*?)(?: \[[^\]]*\])?$",
                behavior.stdout + behavior.stderr, regex.M,
            ),
        }
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=Path)
    parser.add_argument("--agent", type=Path)
    parser.add_argument("--grade", metavar="IMAGE", help="grade the committed fixture instead")
    arguments = parser.parse_args()
    if arguments.grade:
        import asyncio

        print(json.dumps(asyncio.run(grade(arguments.grade)), indent=2))
    else:
        if arguments.start is None or arguments.agent is None:
            parser.error("--start and --agent are required to build the fixture")
        print(json.dumps(write(PILOT.parent, arguments.start, arguments.agent), indent=2))
