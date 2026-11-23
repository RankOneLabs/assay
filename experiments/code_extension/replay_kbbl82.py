"""Build the kbbl build-guard replay fixture from two pinned Oakridge trees.

The replay starts from Oakridge 7fce9e87dd, where subgoals 1-10 of the cohort-5 build
brief were committed. Its task is that brief as the build agent had it (before the
deviations section was appended), asking for subgoal 11: POST /briefs/:id/build and the
wired Run build button. The agent's answer, fc87c8e1c9, refused the build while the
cohort's `current_session_ref` named any live session. The dispatcher writes that field
for planner2 as well as build (subgoal 5 of the same brief), so a planner2 session still
up blocked the operator's Run build. PR #82 round 3 (f1b28459ab) fixed it.

The brief's subgoal 11 spelled the guard as the agent wrote it. `TASK_EDIT` replaces that
clause with its stated intent ("block on this cohort is already building", from the
brief's decisions), so the replay tests whether the model finds planner2's write, not
whether it overrides an explicit instruction.

Fetch both trees with `gh api repos/RankOneLabs/oakridge/tarball/<sha>` and extract each
with `--strip-components=1`. The brief is comms/task-review/briefs/cohort-5-build-brief.md
at 7c33f9913e. Then run from experiments/:

    uv run python -m code_extension.replay_kbbl82 --start <7fce tree> --agent <fc87 tree>

Add `--arm <name>` to build one of the fact-shape arms in `ARMS` as its own scenario,
`kbbl-build-guard-replay-<name>`. Each states planner2's write to the cohort's
`current_session_ref` in one more place; hidden tests and held fixes are the same.
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections.abc import Mapping
from pathlib import Path

from assay.canonical import canonical_json, digest_bytes
from assay.investigations.workflow_correctness import workflow_tree_digest
from code_extension.authoring import unified_patch
from code_extension.fixture import COLOCATED_VISIBLE, PILOT, materialize, read_tree
from code_extension.fixtures import ExtensionScenarioSidecar, touched_paths
from code_extension.replay_kbbl import BUILD_ENTRY, Edit, _apply, relocate, start_tree

NAME = "kbbl-build-guard-replay"
SUBJECT_ID = "oakridge-kbbl-build-guard-replay"
START_SHA = "7fce9e87dd5a7bfcbf0bfef170faaa12bed23a40"
AGENT_SHA = "fc87c8e1c9d1fe89d6768cbf5afa7a8faac3ac9c"
FIX_SHA = "f1b28459ab7fa170d95803df3845b7a384f025cd"  # PR #82 round 3
BRIEF_SHA = "7c33f9913e"
AGENT_FILES = (
    "kbbl/core/pwa/review/brief/BriefReviewView.tsx",
    "kbbl/core/server.ts",
    "kbbl/core/server/app.ts",
    "kbbl/core/server/handlers/builds.ts",
)
COMMS = Path(__file__).resolve().parents[2] / "comms" / "oakridge-replay-pr82r3"
BRIEF = "cohort-5-build-brief.md"
HIDDEN_TEST = "run-build-guard.test.tsx"
REGRESSION_TESTS = (
    "kbbl/core/server/app.test.ts",
    "kbbl/core/db/briefs.test.ts",
    "kbbl/core/orchestrator/state-machine.test.ts",
    "kbbl/core/orchestrator/lifecycle.test.ts",
    "kbbl/core/server/handlers/sessions.model.test.ts",
    "kbbl/core/orchestrator/backends/prompt-loader.test.ts",
)

DISPATCH_COHORT = (
    '        db.prepare("UPDATE cohorts SET current_session_ref = ? WHERE id = ?")'
    ".run(session_ref, inputId);\n"
)
DISPATCH_BUILD = (
    '          db.prepare("UPDATE cohorts SET current_session_ref = ? WHERE id = ?")'
    ".run(session_ref, briefRow.cohort_id);\n"
)
GUARD = (
    "    if (cohort?.current_session_ref) {\n"
    "      const existingSession = manager.get(cohort.current_session_ref);\n"
    '      if (existingSession && existingSession.status !== "ended") {\n'
    '        return c.json({ error: "a build session is already running for this cohort" }, 409);\n'
    "      }\n    }\n"
)
BUILDS = "kbbl/core/server/handlers/builds.ts"
DISPATCHER = "kbbl/core/orchestrator/backends/dispatcher.ts"

# Port of f1b28459ab's server part: record which stage owns the cohort's ref, and let only
# a build session block Run build.
FIX: tuple[Edit, ...] = (
    (DISPATCHER, DISPATCH_COHORT,
     '        db.prepare(\n'
     '          "UPDATE cohorts SET current_session_ref = ?, current_session_stage = ? '
     'WHERE id = ?",\n'
     "        ).run(session_ref, stage.name, inputId);\n"),
    (DISPATCHER, DISPATCH_BUILD,
     '          db.prepare(\n'
     '            "UPDATE cohorts SET current_session_ref = ?, current_session_stage = ? '
     'WHERE id = ?",\n'
     "          ).run(session_ref, stage.name, briefRow.cohort_id);\n"),
    (BUILDS,
     "    interface CohortRefRow { current_session_ref: string | null }\n"
     "    const cohort = db\n"
     '      .prepare<CohortRefRow, [string]>('
     '"SELECT current_session_ref FROM cohorts WHERE id = ?")\n',
     "    // Only a build session on the cohort blocks; planner2 writes the same ref.\n"
     "    interface CohortRefRow {\n      current_session_ref: string | null;\n"
     "      current_session_stage: string | null;\n    }\n"
     "    const cohort = db\n"
     "      .prepare<CohortRefRow, [string]>(\n"
     '        "SELECT current_session_ref, current_session_stage FROM cohorts WHERE id = ?",\n'
     "      )\n"),
    (BUILDS, "    if (cohort?.current_session_ref) {\n",
     '    if (cohort?.current_session_ref && cohort.current_session_stage === "build") {\n'),
    ("kbbl/core/types/task-tracker.ts",
     "  current_session_ref: z.string().nullable(),\n  created_at: z.string(),\n});\n"
     "export type Cohort",
     "  current_session_ref: z.string().nullable(),\n"
     "  current_session_stage: z.string().nullable().optional(),\n"
     "  created_at: z.string(),\n});\nexport type Cohort"),
)
FIX_MIGRATION = (
    "kbbl/core/db/migrations/009_session_stage.sql",
    "-- Which stage owns cohorts.current_session_ref: planner2 and build both write it.\n"
    "ALTER TABLE cohorts ADD COLUMN current_session_stage TEXT;\n",
)

# planner2's ref goes to its own column, so current_session_ref names only builds.
ALTERNATIVE_COLUMN: tuple[Edit, ...] = ((
    DISPATCHER, DISPATCH_COHORT,
    "        // planner2 keeps its own ref: current_session_ref on a cohort is the build's.\n"
    '        db.prepare("UPDATE cohorts SET planner2_session_ref = ? WHERE id = ?")'
    ".run(session_ref, inputId);\n",
),)
ALTERNATIVE_COLUMN_MIGRATION = (
    "kbbl/core/db/migrations/009_planner2_session_ref.sql",
    "-- planner2's session, kept apart from the build's current_session_ref.\n"
    "ALTER TABLE cohorts ADD COLUMN planner2_session_ref TEXT;\n",
)

# Approval ends planner2's claim on the cohort: clear the ref as the cohort enters building.
ALTERNATIVE_CLEAR: tuple[Edit, ...] = ((
    "kbbl/core/server/handlers/brief-status.ts",
    "            \"UPDATE cohorts SET status = 'building' WHERE id = ? "
    "AND status = 'brief_review'\",\n",
    "            // planner2's ref is done with once the brief is approved; only a build\n"
    "            // session may hold the cohort from here on.\n"
    "            \"UPDATE cohorts SET status = 'building', current_session_ref = NULL \"\n"
    "              + \"WHERE id = ? AND status = 'brief_review'\",\n",
),)

# The agent's commit with the live-session guard left out.
NO_GUARD: tuple[Edit, ...] = ((BUILDS, GUARD, "    void manager;\n    void cohort;\n"),)

# The agent made createApp's dispatcher required but left app.test.ts calling it without
# one, which fails the typecheck. Every held tree passes a stub there, and the file is an
# editable visible test (COLOCATED_VISIBLE), since a correct fix may have to do the same.
APP_TEST = "kbbl/core/server/app.test.ts"
APP_TEST_EDIT: tuple[Edit, ...] = ((
    APP_TEST, "    configPath,\n    db,\n  });",
    "    configPath,\n    db,\n    dispatcher: {} as never,\n  });",
),)

# An earlier subgoal made updateBriefDebrief's third argument an object; briefs.test.ts
# still passed a string, failing its test and the typecheck at the start commit. Oakridge
# later changed these two calls the same way.
STALE_BRIEFS_TEST = "kbbl/core/db/briefs.test.ts"
START_FIXES: tuple[Edit, ...] = (
    (STALE_BRIEFS_TEST, 'updateBriefDebrief(db, "b7", "All went well")',
     'updateBriefDebrief(db, "b7", { debrief: "All went well" })'),
    (STALE_BRIEFS_TEST, 'updateBriefDebrief(db, "nope", "debrief")',
     'updateBriefDebrief(db, "nope", { debrief: "debrief" })'),
)


# Fact-shape arms. The brief states planner2's write once, in subgoal 7 ("writes
# `current_session_ref` onto the input artifact (specs for planner1, cohorts for planner2 and
# build)"), and the dispatcher's write names build in a comment but planner2 nowhere: it
# branches on the stage's input type. Each arm adds the fact in one more place.
WRITE_COHORT = '      } else if (stage.input_artifact_type === "cohort") {\n' + DISPATCH_COHORT
NEAR_ASK = (
    "else `dispatcher.dispatch('build', brief_id)` and return `{session_ref}`.\n",
    "else `dispatcher.dispatch('build', brief_id)` and return `{session_ref}`.\n"
    "    - The dispatcher writes the cohort's `current_session_ref` for planner2 as well as "
    "for build (subgoal 7).\n",
)
ARMS: dict[str, dict[str, object]] = {
    # The brief's own statement, repeated as a bullet of subgoal 11.
    "near-ask": {"task": NEAR_ASK, "tree": ()},
    # A comment at the cohort branch of the write, like the build branch's.
    "write-comment": {"task": None, "tree": ((
        DISPATCHER, WRITE_COHORT,
        '      } else if (stage.input_artifact_type === "cohort") {\n'
        "        // planner2 \u2192 the cohort's own ref, the column a build dispatch also writes\n"
        + DISPATCH_COHORT,
    ),)},
    # The write branches on planner2 by name: the seeded stages make it the same branch.
    "write-named": {"task": None, "tree": ((
        DISPATCHER, WRITE_COHORT,
        '      } else if (stage.name === "planner2") {\n' + DISPATCH_COHORT,
    ),)},
}


def scenario_name(arm: str = "") -> str:
    return f"{NAME}-{arm}" if arm else NAME


def subject_id(arm: str = "") -> str:
    return f"{SUBJECT_ID}-{arm}" if arm else SUBJECT_ID


def trees(start: Path, agent: Path, arm: str = "") -> dict[str, dict[str, str]]:
    base = _apply(start_tree(start), START_FIXES)
    if arm:
        base = _apply(base, ARMS[arm]["tree"])  # type: ignore[arg-type]
    mistake = dict(base)
    for path in AGENT_FILES:
        mistake[path] = (agent / path).read_text(encoding="utf-8")
    mistake = _apply(mistake, APP_TEST_EDIT)
    reference = _apply(mistake, FIX)
    reference[FIX_MIGRATION[0]] = FIX_MIGRATION[1]
    column = _apply(mistake, ALTERNATIVE_COLUMN)
    column[ALTERNATIVE_COLUMN_MIGRATION[0]] = ALTERNATIVE_COLUMN_MIGRATION[1]
    return {
        "start": base,
        "agent": mistake,
        "reference": reference,
        "alternative-column": column,
        "alternative-clear": _apply(mistake, ALTERNATIVE_CLEAR),
        "no-guard": _apply(mistake, NO_GUARD),
    }


FRAMING = (
    "Subgoals 1-10 of the build brief below are already implemented and committed in this "
    "repository. Implement subgoal 11. createApp takes the dispatcher as a `dispatcher` "
    "dependency.\n\n"
)
LIVE = "409 if a build is already running for this cohort;"
# Subgoal 11 spelled the guard as "any live session in current_session_ref", the reading
# the agent implemented. The edit keeps the brief's own intent for it (decisions: the ref
# "lets /briefs/:id/build block on 'this cohort is already building'").
TASK_EDIT = (
    "409 if the cohort already has a non-null `current_session_ref` whose session is still "
    "`live`;",
    LIVE,
)
DEVIATIONS = "\n## Deviations from plan\n"


def task_text(brief: str, arm: str = "") -> str:
    """The brief as the agent had it, with the framing line and the one edited clause."""
    if brief.count(DEVIATIONS) != 1:
        raise ValueError("brief does not contain the deviations section exactly once")
    brief = brief[: brief.index(DEVIATIONS)].rstrip("\n") + "\n"
    old, new = TASK_EDIT
    if brief.count(old) != 1:
        raise ValueError("brief does not contain the guard clause exactly once")
    task = FRAMING + brief.replace(old, new)
    edit = ARMS[arm]["task"] if arm else None
    if edit:
        before, after = edit  # type: ignore[misc]
        if task.count(before) != 1:
            raise ValueError(f"task does not contain the {arm} anchor exactly once")
        task = task.replace(before, after)
    return task


def hidden_files(start: Mapping[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    test = (COMMS / HIDDEN_TEST).read_text(encoding="utf-8")
    new_behavior = {f"tests/hidden/new-behavior/{HIDDEN_TEST}": test}
    regression = {}
    for path in REGRESSION_TESTS:
        target = "tests/hidden/regression/" + path
        regression[target] = relocate(start[path], path, target)
    return regression, new_behavior


PATCH_NAMES = {
    "reference": "reference.patch",
    "agent": "negative.patch",
    "no-guard": "no-guard.patch",
    "alternative-column": "alternative-column.patch",
    "alternative-clear": "alternative-clear.patch",
}


def write(destination: Path, start: Path, agent: Path, arm: str = "") -> dict[str, object]:
    built = trees(start, agent, arm)
    base = built["start"]
    root = destination / scenario_name(arm)
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
    patches = {}
    for label, name in PATCH_NAMES.items():
        patch = unified_patch(base, built[label])
        (root / "patches" / name).write_text(patch, encoding="utf-8")
        patches[name] = patch
    task = task_text((COMMS / BRIEF).read_text(encoding="utf-8"), arm)
    (root / "task.md").write_text(task, encoding="utf-8")
    (root / "README.md").write_text(readme(arm), encoding="utf-8")
    qualification = root / "qualification"
    qualification.mkdir(exist_ok=True)
    sidecar = _sidecar(base, patches, arm)
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
        "visible_tests": len(COLOCATED_VISIBLE[scenario_name(arm)].select(base)),
        "regression_digest": digest_bytes(canonical_json(regression)),
    }


ARM_NOTES = {
    "near-ask": (
        "the task adds one bullet to subgoal 11: \"The dispatcher writes the cohort's "
        "`current_session_ref` for planner2 as well as for build (subgoal 7).\""
    ),
    "write-comment": (
        "the dispatcher's cohort branch of the `current_session_ref` write carries a comment "
        "naming planner2 and saying a build dispatch writes the same column"
    ),
    "write-named": (
        "the dispatcher's cohort branch of the `current_session_ref` write tests "
        "`stage.name === \"planner2\"` instead of the input type; the seeded stages take the "
        "same branch"
    ),
}


def readme(arm: str = "") -> str:
    if not arm:
        return README
    head = (
        f"# {scenario_name(arm)}\n\nFact-shape arm `{arm}` of {NAME}: {ARM_NOTES[arm]}. "
        "Everything else, including hidden tests and held fixes, is built the same way.\n"
    )
    return head + README[README.index("\n", README.index("\n") + 1):]


README = f"""# {NAME}

A replay of a real agent mistake in Oakridge, with one arm (`baseline`).

Do not publish this fixture content, including task text, hidden tests and solution
patches.

- Start tree: Oakridge {START_SHA} (subgoals 1-10 of the cohort-5 build brief), as kbbl/
  plus the root package.json, tsconfig.json and README.md. bun.lock is left out; the image
  carries kbbl's locked dependencies (`integrations/pier/kbbl_replay/`), unchanged from
  this commit to the #99 replay's.
- Task: the cohort-5 build brief as the agent had it ({BRIEF_SHA} without the deviations
  section appended after the build), asking for subgoal 11, with one framing paragraph.
  Subgoal 11's guard clause is replaced by its stated intent (`TASK_EDIT`).
- The agent's answer, {AGENT_SHA}, refused Run build while the cohort's
  `current_session_ref` named any live session. The dispatcher also writes that field for
  planner2, so a planner2 session still up blocked the build. {FIX_SHA} (PR #82 round 3)
  fixed it.

Held patches (each also passes a dispatcher stub in app.test.ts, which the agent's
required `dispatcher` dependency left failing the typecheck):
- reference.patch (reference): the agent's commit plus a port of the fix's server part: a
  `current_session_stage` column written by the dispatcher, and a guard that only counts a
  build session.
- negative.patch (incomplete): the agent's commit; the planner2 cases fail.
- no-guard.patch (incomplete): the agent's commit without the live-session guard; the
  live-build case fails.
- alternative-column.patch (reference): planner2 writes its ref to its own column.
- alternative-clear.patch (reference): approval clears the cohort's ref.

Grading:
- `new_behavior` runs `tests/hidden/new-behavior/{HIDDEN_TEST}` against the real app,
  session manager, dispatcher, cohort 3's bootstrap and BriefReviewView in jsdom. The
  cohort is dispatched to planner2, the brief posted over HTTP and approved through PATCH
  /briefs/:id/status, with the brief.approved build hook not wired (an automatic dispatch
  that failed). Run build must start a build while planner2's session is still up, both
  over HTTP and from the view's button; must be refused with 409 while a build session is
  live; must start a new build once that one has ended; and must answer 404 for a missing
  brief and 409 for one not approved. KBBL_PROMPTS_DIR points at kbbl/prompts, because the
  loader's default path at this commit resolves one directory too high.
- `hidden_regression` runs six of kbbl's own test files, relocated:
  {", ".join(Path(path).name for path in REGRESSION_TESTS)}.
- `visible_regression` is kbbl's colocated bun suite (`COLOCATED_VISIBLE` in
  `code_extension/fixture.py`), restored before grading. It leaves out the PWA's vitest
  tests and app.test.ts, which a fix that makes `dispatcher` required has to edit.

Adaptations:
- tsconfig.json drops `typeRoots`, because the image owns /node_modules/@types. It also
  excludes the PWA's vitest and vite files, because the image has neither.
- `{BUILD_ENTRY}` is added, because the evaluator's build check bundles `src/` and kbbl
  has none.
- kbbl/core/db/briefs.test.ts passes an object to updateBriefDebrief in its two calls, as
  Oakridge later did. An earlier subgoal changed that argument from a string, so at the
  start commit the file failed its test and the typecheck.

Generated by `python -m code_extension.replay_kbbl82`; repository/, hidden/, patches/ and
this file are not edited by hand.
"""

EXISTING = "kbbl's existing server, database, orchestrator and session behavior is unchanged."


def _sidecar(
    base: Mapping[str, str], patches: Mapping[str, str], arm: str = "",
) -> ExtensionScenarioSidecar:
    intents = {
        "reference.patch": ("reference", "The agent's commit plus a port of PR #82 round 3."),
        "negative.patch": ("incomplete", "The agent's commit: a live planner2 session blocks."),
        "no-guard.patch": ("incomplete", "The agent's commit without the live-build guard."),
        "alternative-column.patch": (
            "reference", "The agent's commit; planner2 writes its ref to its own column.",
        ),
        "alternative-clear.patch": (
            "reference", "The agent's commit; approval clears the cohort's planner2 ref.",
        ),
    }
    zero = "sha256:" + "0" * 64
    unrelated = {"visible_regression": "passed", "hidden_regression": "passed"}
    return ExtensionScenarioSidecar.model_validate({
        "subject_id": subject_id(arm),
        "writable_implementation_scope": ["docs/", "kbbl/"],
        "protected_assets": {
            "test_files": [],
            "dependency_files": ["package.json"],
            "configuration_files": ["tsconfig.json"],
        },
        "public_requirements": [LIVE],
        "preexisting_behaviors": [EXISTING],
        "test_assertions": [
            {"assertion_id": "planner2-does-not-block-build", "group_name": "new_behavior",
             "visibility": "hidden"},
            {"assertion_id": "live-build-refused", "group_name": "new_behavior",
             "visibility": "hidden"},
            {"assertion_id": "ended-build-allows-rerun", "group_name": "new_behavior",
             "visibility": "hidden"},
            {"assertion_id": "kbbl-regressions", "group_name": "hidden_regression",
             "visibility": "hidden"},
            {"assertion_id": "kbbl-visible-suite", "group_name": "visible_regression",
             "visibility": "visible"},
        ],
        "requirements_to_tests": [
            {"assertion_id": "planner2-does-not-block-build",
             "citation_kind": "public_requirement", "citation": LIVE},
            {"assertion_id": "live-build-refused", "citation_kind": "public_requirement",
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
            {"patch_name": name, "intent": intents[name][1], "intended_group": "new_behavior",
             "unrelated_results": unrelated}
            for name in ("negative.patch", "no-guard.patch")
        ],
        "provenance": {
            "extraction_invocation": (
                f"gh api repos/RankOneLabs/oakridge/tarball/{START_SHA} (and {AGENT_SHA}), "
                "each extracted with tar --strip-components=1; then uv run python -m "
                "code_extension.replay_kbbl82 --start <tree> --agent <tree>"
                + (f" --arm {arm}" if arm else "")
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
                "briefs.test.ts's two updateBriefDebrief calls pass an object, as Oakridge "
                "later did; the start commit failed its test and the typecheck.",
                *([f"Fact-shape arm {arm}: {ARM_NOTES[arm]}."] if arm else []),
            ],
            "start_tree_digest": workflow_tree_digest(base),
            "start_file_count": len(base),
            "start_total_bytes": sum(len(text.encode()) for text in base.values()),
            "dependency_lock_digests": {},
        },
    })


def manifest_scope(
    subject: str, repository: Mapping[str, str]
) -> tuple[str, tuple[str, ...]] | None:
    """The replay's Oakridge pin and the vendored files that come from it, or None."""
    if subject not in {SUBJECT_ID, *(f"{SUBJECT_ID}-{arm}" for arm in ARMS)}:
        return None
    return START_SHA, tuple(sorted(path for path in repository if path != BUILD_ENTRY))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=Path)
    parser.add_argument("--agent", type=Path)
    parser.add_argument("--grade", metavar="IMAGE", help="grade the committed fixture instead")
    parser.add_argument("--extra", type=Path, help="with --grade, also grade this folder's *.patch")
    parser.add_argument("--arm", default="", choices=["", *ARMS], help="a fact-shape arm")
    arguments = parser.parse_args()
    if arguments.grade:
        import asyncio

        from code_extension.replay_kbbl import grade

        name = scenario_name(arguments.arm)
        print(json.dumps(asyncio.run(grade(arguments.grade, arguments.extra, name)), indent=2))
    else:
        if arguments.start is None or arguments.agent is None:
            parser.error("--start and --agent are required to build the fixture")
        built = write(PILOT.parent, arguments.start, arguments.agent, arguments.arm)
        print(json.dumps(built, indent=2))
