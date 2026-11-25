"""Build the artifact-release replay fixture from a pinned Oakridge tree.

The replay starts from Oakridge 71edf9d5a1, the parent of #417. At that commit an execution
workflow (`artifactContractExecutionWorkflow`) returned as soon as its executor ended, so a
gated artifact whose agent session ended before the reviewer decided was abandoned. #417
(0a2a23249e, agent-written) kept the execution waiting only when the executor's terminal
observation was `succeeded`. But a closed kbbl session observes as `cancelled`, and so does
Oakridge's own fence of a finished executor, and the coordinator's `terminalFailure` fails a
unit on `cancelled` even when its contract is satisfied. Run 13931230 lost a plan approved
12m35s after emission. fd4f6510e8 (#436) fixed it: keep waiting while every outstanding output
is parked at a gate or handoff, and stop failing a satisfied unit on `cancelled`.

There is no recorded brief for #417, so the task (comms/oakridge-replay-pr436/task.md) states
the behaviour the fix established, in the operator's terms, without naming the mechanism.

Extract the start tree with
`git archive 71edf9d5a1 oakridge-dbos oakridge-core/examples/dev_flow_v11.json package.json
tsconfig.json` and run from experiments/:

    uv run python -m code_extension.replay_pr436 --start <tree>
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections.abc import Mapping
from pathlib import Path

from assay.canonical import canonical_json, digest_bytes
from assay.investigations.workflow_correctness import workflow_tree_digest
from assay.repository import validate_repository
from code_extension.authoring import unified_patch
from code_extension.fixture import COLOCATED_VISIBLE, PILOT, materialize, read_tree
from code_extension.fixtures import ExtensionScenarioSidecar, touched_paths
from code_extension.replay_kbbl import Edit, _apply, relocate

NAME = "artifact-release-replay"
SUBJECT_ID = "oakridge-dbos-artifact-release-replay"
START_SHA = "71edf9d5a16281102301381f7094432e4bfadfdc"
AGENT_SHA = "0a2a23249eccc68ad1c693ad62698dfe38f51342"  # #417
FIX_SHA = "fd4f6510e858c6ae2e29a4ec1d4c4a11fe75477e"  # #436
COMMS = Path(__file__).resolve().parents[2] / "comms" / "oakridge-replay-pr436"
HIDDEN_TEST = "gate-outlives-session.test.ts"
DEV_FLOW = "oakridge-core/examples/dev_flow_v11.json"
ROOT_FILES = ("package.json", "tsconfig.json")
REGRESSION_TESTS = tuple(
    f"oakridge-dbos/tests/{name}.test.ts"
    for name in (
        "artifact-callback", "gate-resume", "handoff-complete", "kbbl-adapter",
        "stage-rerun", "unit-rerun", "resolve-execution", "materialize-units",
    )
)
# A fix may change evaluateExecutionArtifactContract's signature, as #436 did.
EDITABLE_TESTS = ("oakridge-dbos/tests/evaluate-artifacts.test.ts",)
BUILD_ENTRY = "src/evaluator-build.ts"
BUILD_ENTRY_SOURCE = (
    "// Evaluator build entry for this replay; not part of Oakridge. The evaluator bundles\n"
    "// src/ to check that the artifact contracts and HTTP surface still build. The workflow\n"
    "// modules import the DBOS SDK, whose optional telemetry requires do not bundle; tsc\n"
    "// checks them instead.\n"
    'export * from "../oakridge-dbos/src/contracts/evaluate-artifacts";\n'
    'export { createArtifactCallbackApp } from "../oakridge-dbos/src/http/artifact-callback";\n'
    'export { createGateResumeApp } from "../oakridge-dbos/src/http/gate-resume";\n'
)

EVALUATE = "oakridge-dbos/src/contracts/evaluate-artifacts.ts"
EXECUTOR = "oakridge-dbos/src/workflows/executor-topology.ts"
PRODUCTION = "oakridge-dbos/src/workflows/production-topology.ts"

EXECUTION_IMPORT = 'import type { ExpectedArtifactContract } from "../domain/execution";\n'
CONTRACT_IMPORT = (
    'import { evaluateExecutionArtifactContract } from "../contracts/evaluate-artifacts";\n'
)
RELEASES = "  const releases: ArtifactReleaseState[] = [];\n"
EMITTED = (
    "      } else {\n"
    "        releases.push(message.release);\n"
    "      }\n"
    '    } else if (message.kind === "artifact_released") {\n'
    '      releases.push({ kind: "released", artifact: message.artifact });\n'
)
GATE_START = (
    '      if (message.release.kind === "waiting_gate") {\n'
    "        await DBOS.startWorkflow(gateRelayWorkflow"
)
TERMINAL = (
    "      const contract = evaluateExecutionArtifactContract(input.outputs, releases, "
    "input.request.expected_artifacts);\n"
    "      return { external_reference: externalReference, contract, terminal_observation: "
    "message.observation };\n"
)
SATISFIED = (
    "      await fenceExecutorStep({ execution_id: input.request.execution_id, executor_type: "
    "input.request.executor_type, external_reference: externalReference });\n"
    "      return { external_reference: externalReference, contract, "
    "terminal_observation: null };\n"
)
WAIT_ON_TERMINAL = (
    "      terminalObservation = message.observation;\n"
    "      const contract = evaluateExecutionArtifactContract(input.outputs, releases, "
    "input.request.expected_artifacts);\n"
    "      if (!shouldAwaitArtifactRelease(@ARGS@)) {\n"
    "        return { external_reference: externalReference, contract, terminal_observation: "
    "message.observation };\n"
    "      }\n"
    "      continue;\n"
)
FENCE_ONCE = (
    "      if (!terminalObservation) await fenceExecutorStep({ execution_id: "
    "input.request.execution_id, executor_type: input.request.executor_type, "
    "external_reference: externalReference });\n"
    "      return { external_reference: externalReference, contract, terminal_observation: "
    "terminalObservation };\n"
)
EVAL_END = (
    "releasedByOutput.get(output.name)).filter((artifact): artifact is ArtifactRevision => "
    "artifact !== undefined) };\n};\n"
)
CANCELLED_FAILS = (
    '  if (result.terminal_observation?.kind === "cancelled") return { kind: "cancelled", '
    "reason: result.terminal_observation.detail };\n"
)

# 0a2a23249e's wait: keep waiting after the executor ends only if it ended `succeeded`.
AGENT: tuple[Edit, ...] = (
    (EVALUATE, EXECUTION_IMPORT,
     'import type { ExecutorTerminalObservation, ExpectedArtifactContract } from '
     '"../domain/execution";\n'),
    (EVALUATE, EVAL_END, EVAL_END + "\n"
     "export const shouldAwaitArtifactRelease = (contract: ExecutionContractState, "
     "observation: ExecutorTerminalObservation): boolean =>\n"
     '  contract.kind === "waiting_artifacts" && observation.kind === "succeeded";\n'),
    (EXECUTOR, CONTRACT_IMPORT,
     "import { evaluateExecutionArtifactContract, shouldAwaitArtifactRelease } from "
     '"../contracts/evaluate-artifacts";\n'),
    (EXECUTOR, RELEASES,
     RELEASES + "  let terminalObservation: ExecutorTerminalObservation | null = null;\n"),
    (EXECUTOR, TERMINAL, WAIT_ON_TERMINAL.replace("@ARGS@", "contract, message.observation")),
    (EXECUTOR, SATISFIED, FENCE_ONCE),
)

AWAIT_DOC = (
    "\n/**\n"
    " * Whether an execution should keep waiting now that its executor has ended: only while\n"
    " * every output it still owes has an artifact parked at a gate or handoff, which a\n"
    " * reviewer can still release. An output with nothing emitted can only come from the\n"
    " * agent, and the agent has gone.\n"
    " */\n"
)


def _await_on_parked(quantifier: str) -> str:
    return (
        EVAL_END + AWAIT_DOC
        + "export const shouldAwaitArtifactRelease = (contract: ExecutionContractState, "
        "releases: readonly ArtifactReleaseState[]): "
        "boolean => {\n"
        '  if (contract.kind !== "waiting_artifacts") return false;\n'
        "  const parked = new Set(releases.filter((release) => release.kind !== \"released\")"
        ".map((release) => `${release.artifact.unit_id}:${release.artifact.output_name}`));\n"
        "  return contract.missing_outputs.length > 0 && "
        f"contract.missing_outputs.{quantifier}((output) => parked.has(output));\n"
        "};\n"
    )


KEEP_PARKED = (
    "      releases = [...releases.filter((candidate) => "
    "candidate.artifact.unit_id !== message.release.artifact.unit_id "
    "|| candidate.artifact.output_name !== message.release.artifact.output_name), "
    "message.release];\n"
)


def _wait_on_parked(quantifier: str) -> tuple[Edit, ...]:
    return (
        (EVALUATE, EVAL_END, _await_on_parked(quantifier)),
        (EXECUTOR, CONTRACT_IMPORT,
         "import { evaluateExecutionArtifactContract, shouldAwaitArtifactRelease } from "
         '"../contracts/evaluate-artifacts";\n'),
        (EXECUTOR, RELEASES,
         "  // Pending waits stay in `releases` so the execution can tell an artifact parked at\n"
         "  // a gate from one never emitted once its executor has ended; contract evaluation\n"
         "  // counts only released artifacts.\n"
         "  let releases: ArtifactReleaseState[] = [];\n"
         "  let terminalObservation: ExecutorTerminalObservation | null = null;\n"),
        (EXECUTOR, '    if (message.kind === "artifact_emitted") {\n' + GATE_START,
         '    if (message.kind === "artifact_emitted") {\n' + KEEP_PARKED + GATE_START),
        (EXECUTOR, EMITTED,
         "      }\n"
         '    } else if (message.kind === "artifact_released") {\n'
         "      releases = [...releases.filter((candidate) => "
         "candidate.artifact.unit_id !== message.artifact.unit_id "
         "|| candidate.artifact.output_name !== message.artifact.output_name), "
         '{ kind: "released", artifact: message.artifact }];\n'),
        (EXECUTOR, TERMINAL, WAIT_ON_TERMINAL.replace("@ARGS@", "contract, releases")),
        (EXECUTOR, SATISFIED, FENCE_ONCE),
    )


# fd4f6510e8's domain part: wait while every outstanding output is parked, and a satisfied
# contract is not failed by the cancellation our own fence produces.
REFERENCE: tuple[Edit, ...] = (
    *_wait_on_parked("every"),
    (PRODUCTION, CANCELLED_FAILS,
     "  // A satisfied unit is not undone by its session closing afterwards: our own fence\n"
     "  // closes it, and kbbl reports any closed session as `cancelled`.\n"),
)
# The wait alone: an approval after the session closed releases the plan, then the
# coordinator fails the unit on the session's `cancelled`.
WAIT_ONLY = _wait_on_parked("every")
# Waits while any output is parked, so a never-emitted output no longer fails promptly.
EAGER = (*_wait_on_parked("some"), REFERENCE[-1])

# A different correct fix: the execution keeps a separate set of parked outputs, and reports
# a closed session as no observation once its contract is satisfied.
PARKED_SET: tuple[Edit, ...] = (
    (EXECUTOR, RELEASES,
     RELEASES
     + "  // Outputs with an artifact waiting on a reviewer; they can still be released after\n"
     "  // the executor has gone.\n"
     "  const parked = new Set<string>();\n"
     "  let terminalObservation: ExecutorTerminalObservation | null = null;\n"),
    (EXECUTOR, '    if (message.kind === "artifact_emitted") {\n' + GATE_START,
     '    if (message.kind === "artifact_emitted") {\n'
     '      if (message.release.kind !== "released") '
     "parked.add(`${message.release.artifact.unit_id}:${message.release.artifact.output_name}`);\n"
     + GATE_START),
    (EXECUTOR, TERMINAL,
     "      terminalObservation = message.observation;\n"
     "      const contract = evaluateExecutionArtifactContract(input.outputs, releases, "
     "input.request.expected_artifacts);\n"
     '      const reviewable = contract.kind === "waiting_artifacts" && '
     "contract.missing_outputs.every((output) => parked.has(output));\n"
     "      if (!reviewable) {\n"
     "        return { external_reference: externalReference, contract, terminal_observation: "
     "message.observation };\n"
     "      }\n"
     "      continue;\n"),
    (EXECUTOR, SATISFIED,
     "      if (!terminalObservation) await fenceExecutorStep({ execution_id: "
     "input.request.execution_id, executor_type: input.request.executor_type, "
     "external_reference: externalReference });\n"
     "      // Everything owed was released: a session closed by now is not a failure.\n"
     "      return { external_reference: externalReference, contract, terminal_observation: "
     'terminalObservation?.kind === "failed" ? terminalObservation : null };\n'),
)

PATCHES: dict[str, tuple[str, tuple[Edit, ...]]] = {
    "reference.patch": ("reference", REFERENCE),
    "alternative-parked-set.patch": ("reference", PARKED_SET),
    "negative.patch": ("incomplete", AGENT),
    "wait-only.patch": ("incomplete", WAIT_ONLY),
    "eager-wait.patch": ("incomplete", EAGER),
}
INTENTS = {
    "reference.patch": "A port of #436's domain part: wait while every missing output is parked; "
    "a satisfied unit is not failed on cancelled.",
    "alternative-parked-set.patch": "A separate parked set; a satisfied execution reports a "
    "closed session as no observation.",
    "negative.patch": "#417's wait: keep waiting only after a succeeded observation.",
    "wait-only.patch": "The reference's wait without the coordinator change: the unit is "
    "cancelled after approval.",
    "eager-wait.patch": "Waits while any output is parked: a never-emitted output no longer "
    "fails the unit promptly.",
}


def adapt_tsconfig(text: str) -> str:
    """The locked image owns the @types tree at /node_modules."""
    config = json.loads(text)
    config["compilerOptions"].pop("typeRoots", None)
    return json.dumps(config, indent=2) + "\n"


def start_tree(source: Path) -> dict[str, str]:
    tree: dict[str, str] = {}
    for path in sorted((source / "oakridge-dbos").rglob("*")):
        if path.is_file():
            tree[path.relative_to(source).as_posix()] = path.read_text(encoding="utf-8")
    tree[DEV_FLOW] = (source / DEV_FLOW).read_text(encoding="utf-8")
    for name in ROOT_FILES:
        tree[name] = (source / name).read_text(encoding="utf-8")
    tree["tsconfig.json"] = adapt_tsconfig(tree["tsconfig.json"])
    tree["oakridge-dbos/tsconfig.json"] = adapt_tsconfig(tree["oakridge-dbos/tsconfig.json"])
    tree[BUILD_ENTRY] = BUILD_ENTRY_SOURCE
    return validate_repository(tree)


def hidden_files(start: Mapping[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    test = (COMMS / HIDDEN_TEST).read_text(encoding="utf-8")
    new_behavior = {f"tests/hidden/new-behavior/{HIDDEN_TEST}": test}
    regression = {}
    for path in REGRESSION_TESTS:
        target = "tests/hidden/regression/" + path
        regression[target] = relocate(start[path], path, target)
    return regression, new_behavior


def write(destination: Path, start: Path) -> dict[str, object]:
    base = start_tree(start)
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
    patches = {}
    for name, (_, edits) in PATCHES.items():
        patch = unified_patch(base, _apply(base, edits))
        (root / "patches" / name).write_text(patch, encoding="utf-8")
        patches[name] = patch
    (root / "task.md").write_text((COMMS / "task.md").read_text(encoding="utf-8"), encoding="utf-8")
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

- Start tree: Oakridge {START_SHA} (the parent of #417), as oakridge-dbos/ plus
  {DEV_FLOW}, which its seed and tests load, and the root package.json and
  tsconfig.json. The image carries oakridge-dbos's locked dependencies
  (`integrations/pier/dbos_replay/`).
- Task: written for this replay (there is no recorded brief for #417). It states the
  behaviour #436 established, in the operator's terms: a gated artifact can be approved
  after its agent's session has ended, and an output never emitted still fails the unit
  promptly.
- The agent's answer, {AGENT_SHA} (#417), kept an execution waiting after its executor
  ended only if the terminal observation was `succeeded`. A closed kbbl session observes
  as `cancelled`, as does Oakridge's own fence of a finished executor; and the
  coordinator's `terminalFailure` failed a satisfied unit on `cancelled`. Run 13931230 lost
  a plan approved 12m35s after emission. {FIX_SHA} (#436) fixed both.

Held patches:
- reference.patch (reference): a port of #436's domain part. Pending gate and handoff
  waits stay in `releases`; after the executor ends, the execution keeps waiting while
  every missing output is parked; `terminalFailure` no longer fails a satisfied unit on
  `cancelled`. #436 also kept waiting on any `succeeded` observation, even with nothing
  emitted; the port leaves that out, so a never-emitted output fails promptly however the
  session ended, as the task states. No hidden case depends on it.
- alternative-parked-set.patch (reference): a separate set of parked outputs, and a
  satisfied execution reports a closed session as no observation.
- negative.patch (incomplete): #417's wait, only after `succeeded`.
- wait-only.patch (incomplete): the reference's wait without the coordinator change.
- eager-wait.patch (incomplete): waits while any output is parked.

Grading:
- `new_behavior` runs `tests/hidden/new-behavior/{HIDDEN_TEST}`: the real
  `productionStageWorkflow` and execution workflows for dev_flow_v11's `plan_writer`
  stage, over an in-memory stand-in for DBOS (`mock.module`), with a scripted executor
  adapter whose fence closes the session as `cancelled`. A plan approved after the session
  closed, or after the agent exited normally, must complete the unit; one approved while
  the agent runs must too; a session closed with nothing emitted, or with one of two
  outputs never emitted, must fail the unit as `required_output_missing` promptly.
- `hidden_regression` runs eight of oakridge-dbos's own test files, relocated:
  {", ".join(Path(path).name for path in REGRESSION_TESTS)}.
- `visible_regression` is oakridge-dbos's tests/ suite (`COLOCATED_VISIBLE` in
  `code_extension/fixture.py`), restored before grading, except evaluate-artifacts.test.ts,
  which a fix that changes `evaluateExecutionArtifactContract` has to edit.

Adaptations:
- Both tsconfig.json files drop `typeRoots`, because the image owns /node_modules/@types.
- `{BUILD_ENTRY}` is added, because the evaluator's build check bundles `src/` and
  Oakridge has none at the root.

Generated by `python -m code_extension.replay_pr436`; repository/, hidden/, patches/ and
this file are not edited by hand.
"""

REQUIREMENT = (
    "An artifact emitted into a gate or a handoff can still be approved after its agent's "
    "session has ended, and that approval releases it and completes the unit."
)
MISSING = (
    "When the agent's session ends and an output the unit owes has never been emitted, the "
    "unit fails as missing output promptly."
)
EXISTING = "Executions, gates, handoffs and the stage coordinator otherwise behave as before."


def _sidecar(base: Mapping[str, str], patches: Mapping[str, str]) -> ExtensionScenarioSidecar:
    zero = "sha256:" + "0" * 64
    unrelated = {"visible_regression": "passed", "hidden_regression": "passed"}
    return ExtensionScenarioSidecar.model_validate({
        "subject_id": SUBJECT_ID,
        "writable_implementation_scope": ["oakridge-dbos/"],
        "protected_assets": {
            "test_files": [],
            "dependency_files": ["package.json"],
            "configuration_files": ["tsconfig.json"],
        },
        "public_requirements": [REQUIREMENT, MISSING],
        "preexisting_behaviors": [EXISTING],
        "test_assertions": [
            {"assertion_id": "approval-after-session-closed", "group_name": "new_behavior",
             "visibility": "hidden"},
            {"assertion_id": "approval-after-normal-exit", "group_name": "new_behavior",
             "visibility": "hidden"},
            {"assertion_id": "never-emitted-fails-promptly", "group_name": "new_behavior",
             "visibility": "hidden"},
            {"assertion_id": "oakridge-dbos-regressions", "group_name": "hidden_regression",
             "visibility": "hidden"},
            {"assertion_id": "oakridge-dbos-visible-suite", "group_name": "visible_regression",
             "visibility": "visible"},
        ],
        "requirements_to_tests": [
            {"assertion_id": "approval-after-session-closed",
             "citation_kind": "public_requirement", "citation": REQUIREMENT},
            {"assertion_id": "approval-after-normal-exit",
             "citation_kind": "public_requirement", "citation": REQUIREMENT},
            {"assertion_id": "never-emitted-fails-promptly",
             "citation_kind": "public_requirement", "citation": MISSING},
            {"assertion_id": "oakridge-dbos-regressions",
             "citation_kind": "preexisting_behavior", "citation": EXISTING},
        ],
        "patch_inventory": [
            {"arm_id": "baseline", "kind": PATCHES[name][0],
             "digest": digest_bytes(patch.encode()), "intent": INTENTS[name],
             "touched_paths": list(touched_paths(patch))}
            for name, patch in sorted(patches.items())
        ],
        "evidence": {key: zero for key in (
            "leak_scan", "access_probe", "no_op", "scripted_submission", "double_reproduction",
        )},
        "tool_instructions": (
            "Work within oakridge-dbos/; keep the root package.json and tsconfig.json "
            "unchanged. Run the tests with bun test from oakridge-dbos/ and "
            "tsc --noEmit -p tsconfig.json from the repository root, then submit with "
            "submit_output."
        ),
        "negative_expectations": [
            {"patch_name": name, "intent": INTENTS[name], "intended_group": "new_behavior",
             "unrelated_results": unrelated}
            for name in ("negative.patch", "wait-only.patch", "eager-wait.patch")
        ],
        "provenance": {
            "extraction_invocation": (
                f"git archive {START_SHA} oakridge-dbos {DEV_FLOW} package.json tsconfig.json; "
                "then uv run python -m code_extension.replay_pr436 --start <tree>"
            ),
            "extraction_rules": [
                f"Vendor oakridge-dbos/, {DEV_FLOW} and the root package.json and "
                f"tsconfig.json from {START_SHA}, unchanged apart from the adaptations.",
                "Keep hidden checks, patches and qualification assets outside repository/.",
            ],
            "licenses": [
                "Oakridge is private source at the pinned commit; no license file is present.",
            ],
            "local_adaptations": [
                "Both tsconfig.json files drop typeRoots.",
                f"{BUILD_ENTRY} is added as the evaluator's bun build entry.",
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
    if subject != SUBJECT_ID:
        return None
    return START_SHA, tuple(sorted(path for path in repository if path != BUILD_ENTRY))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=Path)
    parser.add_argument("--grade", metavar="IMAGE", help="grade the committed fixture instead")
    parser.add_argument("--extra", type=Path, help="with --grade, also grade this folder's *.patch")
    arguments = parser.parse_args()
    if arguments.grade:
        import asyncio

        from code_extension.replay_kbbl import grade

        print(json.dumps(asyncio.run(grade(arguments.grade, arguments.extra, NAME)), indent=2))
    else:
        if arguments.start is None:
            parser.error("--start is required to build the fixture")
        print(json.dumps(write(PILOT.parent, arguments.start), indent=2))
