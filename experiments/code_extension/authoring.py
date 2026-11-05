"""Generate four-shape fixture assets from one task's solution, without any model.

A task supplies its compiler source once. This module derives each arm's start
tree, private patches and sidecar from the pass-through arms, so the arms differ
only in where the stage is registered. Qualification then fills in the evidence.

    uv run python -m code_extension.authoring --scenario stage-status-report
"""
# ruff: noqa: E501 - embedded TypeScript keeps the fixture's own line lengths.

from __future__ import annotations

import argparse
import difflib
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from assay.canonical import canonical_json, digest_bytes
from assay.investigations.workflow_correctness import workflow_tree_digest
from code_extension.fixture import AGENT_TEST_PREFIX, PILOT, materialize, read_tree
from code_extension.fixtures import ExtensionScenarioSidecar, touched_paths

SOURCE_SCENARIO = "stage-pass-through"
SHAPE_ARMS = ("modular", "central", "cross_module", "plugin")
WRITABLE_SCOPE = ("src/", AGENT_TEST_PREFIX)
UNSET_EVIDENCE = "sha256:" + "0" * 64
COMPILE_WORKFLOW = "src/compiler/compile-workflow.ts"
REGISTRATION = "src/compiler/stage-registration.ts"
PLUGIN_CONFIG = "src/compiler/stage-plugin-config.json"
IMPORT_ANCHOR = 'import { selectOutputReleasePolicy } from "../domain/output-release-policy";\n'
REGISTRY_ANCHOR = "export type StageTypeCompilerRegistry = Readonly<Record<string, StageTypeCompiler>>;\n"
ENTRY_ANCHOR = "  [PROVISION_REPOSITORY_REFS_STAGE_TYPE]: repositoryProvisioningStageTypeCompiler,\n"
CASE_ANCHOR = (
    "    case PROVISION_REPOSITORY_REFS_STAGE_TYPE: return repositoryProvisioningStageTypeCompiler;\n"
)
CROSS_MODULE_CALL = "registerBuiltInCompilers(delegatedCompiler, repositoryCompiler)"

Tree = dict[str, str]


@dataclass(frozen=True, slots=True)
class Assertion:
    """One hidden feature check; its id says which failure kind it measures."""

    assertion_id: str
    citation: str


@dataclass(frozen=True, slots=True)
class ShapeTask:
    scenario: str
    subject_id: str
    stage_type: str
    compiler: str
    registration_parameter: str
    imports: str
    compiler_source: str
    new_files: Mapping[str, str]
    wrong_semantics: tuple[str, str, str]
    wrong_semantics_intent: str
    public_requirements: tuple[str, ...]
    assertions: tuple[Assertion, ...]


STATUS_REPORT = ShapeTask(
    scenario="stage-status-report",
    subject_id="oakridge-dbos-stage-status-report",
    stage_type="status_report",
    compiler="statusReportStageTypeCompiler",
    registration_parameter="statusReport",
    imports='import { statusReportDefinitionSchema } from "../validation/status-report";\n',
    compiler_source="""export const statusReportStageTypeCompiler: StageTypeCompiler = {
  compile(stageKey, rawConfig) {
    const parsed = statusReportDefinitionSchema.safeParse(rawConfig);
    if (!parsed.success) return err({ operation: "compile_workflow", stage_key: stageKey, detail: parsed.error.message });
    return ok({
      definition_config: parsed.data,
      materialization: { kind: "scalar" },
      output_release: () => ({ kind: "immediate" }),
    });
  },
};

""",
    new_files={
        "src/validation/status-report.ts": """import { z } from "zod";

export const statusReportDefinitionSchema = z.strictObject({
  channel: z.string().min(1),
  severity: z.enum(["info", "warning", "error"]).default("info"),
  max_items: z.number().int().positive().default(20),
});
""",
    },
    wrong_semantics=(
        "src/validation/status-report.ts",
        "z.strictObject({",
        "z.object({",
    ),
    wrong_semantics_intent="Register the compiler but silently drop unknown fields.",
    public_requirements=(
        "Compile status_report through the built-in dispatch.",
        "Validate channel, severity and max_items, rejecting anything else.",
        "Fill documented defaults into the normalized executor configuration.",
        "Materialize one scalar unit and release every output immediately.",
        "Preserve existing stage types, injected registries and attention validation.",
    ),
    assertions=(
        Assertion(
            "reachability-normal-dispatch",
            "Compile status_report through the built-in dispatch.",
        ),
        Assertion(
            "semantics-explicit-configuration",
            "Fill documented defaults into the normalized executor configuration.",
        ),
        Assertion(
            "semantics-defaults",
            "Fill documented defaults into the normalized executor configuration.",
        ),
        Assertion(
            "semantics-scalar-immediate",
            "Materialize one scalar unit and release every output immediately.",
        ),
        Assertion(
            "semantics-rejects-malformed",
            "Validate channel, severity and max_items, rejecting anything else.",
        ),
        Assertion(
            "semantics-rejects-unknown",
            "Validate channel, severity and max_items, rejecting anything else.",
        ),
        Assertion(
            "semantics-attention",
            "Preserve existing stage types, injected registries and attention validation.",
        ),
    ),
)

COLLECT_ARTIFACTS = ShapeTask(
    scenario="stage-collect-artifacts",
    subject_id="oakridge-dbos-stage-collect-artifacts",
    stage_type="collect_artifacts",
    compiler="collectArtifactsStageTypeCompiler",
    registration_parameter="collectArtifacts",
    imports='import { collectArtifactsDefinitionSchema } from "../validation/collect-artifacts";\n',
    compiler_source="""export const collectArtifactsStageTypeCompiler: StageTypeCompiler = {
  compile(stageKey, rawConfig) {
    const parsed = collectArtifactsDefinitionSchema.safeParse(rawConfig);
    if (!parsed.success) return err({ operation: "compile_workflow", stage_key: stageKey, detail: parsed.error.message });
    return ok({
      definition_config: parsed.data,
      materialization: { kind: "artifact_collection", over: parsed.data.over, id_path: parsed.data.id_path },
      output_release: () => ({ kind: "immediate" }),
    });
  },
};

""",
    new_files={
        "src/validation/collect-artifacts.ts": """import { z } from "zod";
import { slotBindingSchema } from "./slot-binding";

export const collectArtifactsDefinitionSchema = z.strictObject({
  over: slotBindingSchema.refine(
    (binding) => binding.from !== "literal" && binding.from !== "item",
    "over must be able to resolve to a collection",
  ),
  id_path: z.string().regex(/^\\/.+/, "id_path must be an absolute JSON pointer to a field"),
});
""",
    },
    wrong_semantics=(
        COMPILE_WORKFLOW,
        'materialization: { kind: "artifact_collection", over: parsed.data.over, '
        'id_path: parsed.data.id_path },',
        'materialization: { kind: "scalar" },',
    ),
    wrong_semantics_intent="Register the compiler but materialize one scalar unit.",
    public_requirements=(
        "Compile collect_artifacts through the built-in dispatch.",
        "Validate over and id_path, rejecting anything else.",
        "Materialize an artifact collection over the configured binding and id_path.",
        "Keep the configuration in the executor contract and release outputs immediately.",
        "Preserve existing stage types, injected registries and attention validation.",
    ),
    assertions=(
        Assertion(
            "reachability-normal-dispatch",
            "Compile collect_artifacts through the built-in dispatch.",
        ),
        Assertion(
            "semantics-artifact-collection",
            "Materialize an artifact collection over the configured binding and id_path.",
        ),
        Assertion(
            "semantics-executor-configuration",
            "Keep the configuration in the executor contract and release outputs immediately.",
        ),
        Assertion(
            "semantics-immediate-release",
            "Keep the configuration in the executor contract and release outputs immediately.",
        ),
        Assertion(
            "semantics-rejects-malformed",
            "Validate over and id_path, rejecting anything else.",
        ),
        Assertion(
            "semantics-rejects-unknown",
            "Validate over and id_path, rejecting anything else.",
        ),
        Assertion(
            "semantics-attention",
            "Preserve existing stage types, injected registries and attention validation.",
        ),
    ),
)

TASKS = {task.scenario: task for task in (STATUS_REPORT, COLLECT_ARTIFACTS)}


def _replace(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f"authoring anchor must match once: {old!r}")
    return source.replace(old, new)


def _define(tree: Tree, task: ShapeTask) -> Tree:
    """Add the compiler to every arm, with no registration yet."""
    source = _replace(tree[COMPILE_WORKFLOW], IMPORT_ANCHOR, IMPORT_ANCHOR + task.imports)
    source = _replace(source, REGISTRY_ANCHOR, task.compiler_source + REGISTRY_ANCHOR)
    return {**tree, **task.new_files, COMPILE_WORKFLOW: source}


def _entry(task: ShapeTask) -> str:
    return f"  {task.stage_type}: {task.compiler},\n"


def _make_available(tree: Tree, task: ShapeTask) -> Tree:
    """Plugin: the loader can see the compiler, but configuration has not enabled it."""
    source = _replace(tree[COMPILE_WORKFLOW], ENTRY_ANCHOR, ENTRY_ANCHOR + _entry(task))
    return {**tree, COMPILE_WORKFLOW: source}


def _register_modular(tree: Tree, task: ShapeTask) -> Tree:
    return _make_available(tree, task)


def _register_central(tree: Tree, task: ShapeTask) -> Tree:
    case = f'    case "{task.stage_type}": return {task.compiler};\n'
    return {
        **tree,
        COMPILE_WORKFLOW: _replace(tree[COMPILE_WORKFLOW], CASE_ANCHOR, CASE_ANCHOR + case),
    }


def _register_cross_module(tree: Tree, task: ShapeTask) -> Tree:
    parameter = task.registration_parameter
    registration = _replace(
        tree[REGISTRATION],
        "  repository: StageTypeCompiler,\n",
        f"  repository: StageTypeCompiler,\n  {parameter}: StageTypeCompiler,\n",
    )
    registration = _replace(
        registration,
        "  [PROVISION_REPOSITORY_REFS_STAGE_TYPE]: repository,\n",
        f"  [PROVISION_REPOSITORY_REFS_STAGE_TYPE]: repository,\n"
        f"  {task.stage_type}: {parameter},\n",
    )
    call = CROSS_MODULE_CALL.removesuffix(")") + f", {task.compiler})"
    return {
        **tree,
        REGISTRATION: registration,
        COMPILE_WORKFLOW: _replace(tree[COMPILE_WORKFLOW], CROSS_MODULE_CALL, call),
    }


def _register_plugin(tree: Tree, task: ShapeTask) -> Tree:
    available = _make_available(tree, task)
    enabled = _replace(
        tree[PLUGIN_CONFIG],
        '"provision_repository_refs"]',
        f'"provision_repository_refs", "{task.stage_type}"]',
    )
    return {**available, PLUGIN_CONFIG: enabled}


REGISTER: dict[str, Callable[[Tree, ShapeTask], Tree]] = {
    "modular": _register_modular,
    "central": _register_central,
    "cross_module": _register_cross_module,
    "plugin": _register_plugin,
}


def unified_patch(before: Tree, after: Tree) -> str:
    """The same `diff --git` shape as the committed patches, applied by `git apply`."""
    chunks: list[str] = []
    for path in sorted(before.keys() | after.keys()):
        old, new = before.get(path), after.get(path)
        if old == new:
            continue
        if new is None:
            raise ValueError(f"authored patches never delete a file: {path}")
        header = f"diff --git a/{path} b/{path}\n"
        if old is None:
            header += "new file mode 100644\n"
        body = difflib.unified_diff(
            (old or "").splitlines(keepends=True), new.splitlines(keepends=True),
            "/dev/null" if old is None else f"a/{path}", f"b/{path}",
        )
        chunks.append(header + "".join(line for line in body))
    return "".join(chunks)


def arm_patches(tree: Tree, task: ShapeTask, arm: str) -> dict[str, str]:
    """Reference, missing-integration and wrong-semantics patches for one arm."""
    defined = _define(tree, task)
    reference = REGISTER[arm](defined, task)
    path, old, new = task.wrong_semantics
    wrong = {**reference, path: _replace(reference[path], old, new)}
    missing = _make_available(defined, task) if arm == "plugin" else defined
    return {
        f"{arm}.reference.patch": unified_patch(tree, reference),
        f"{arm}.negative.patch": unified_patch(tree, missing),
        f"{arm}.wrong-semantics.patch": unified_patch(tree, wrong),
    }


def _sidecar(
    template: ExtensionScenarioSidecar, task: ShapeTask, arm: str, tree: Tree,
    patches: Mapping[str, str],
) -> ExtensionScenarioSidecar:
    missing = (
        "Define the compiler and offer it to the loader, but do not enable it."
        if arm == "plugin" else "Define the compiler but omit dispatch registration."
    )
    intents = {
        f"{arm}.reference.patch": ("reference", "Complete the task in this arm's architecture."),
        f"{arm}.negative.patch": ("incomplete", missing),
        f"{arm}.wrong-semantics.patch": ("incomplete", task.wrong_semantics_intent),
    }
    regression = template.preexisting_behaviors[0]
    unrelated = {"hidden_regression": "passed", "visible_regression": "passed"}
    values = template.model_dump(mode="json")
    values.update({
        "subject_id": task.subject_id,
        "writable_implementation_scope": list(WRITABLE_SCOPE),
        "public_requirements": list(task.public_requirements),
        "test_assertions": [
            {"assertion_id": "visible-regression", "group_name": "visible_regression",
             "visibility": "visible"},
            {"assertion_id": "hidden-regression", "group_name": "hidden_regression",
             "visibility": "hidden"},
            *({"assertion_id": item.assertion_id, "group_name": "new_behavior",
               "visibility": "hidden"} for item in task.assertions),
        ],
        "requirements_to_tests": [
            {"assertion_id": "visible-regression", "citation": regression,
             "citation_kind": "preexisting_behavior"},
            {"assertion_id": "hidden-regression", "citation": regression,
             "citation_kind": "preexisting_behavior"},
            *({"assertion_id": item.assertion_id, "citation": item.citation,
               "citation_kind": "public_requirement"} for item in task.assertions),
        ],
        "patch_inventory": [
            {"arm_id": arm, "kind": kind, "digest": digest_bytes(patches[name].encode()),
             "intent": intent, "touched_paths": list(touched_paths(patches[name]))}
            for name, (kind, intent) in intents.items()
        ],
        "negative_expectations": [
            {"patch_name": f"{arm}.negative.patch", "intent": missing,
             "intended_group": "new_behavior", "unrelated_results": unrelated},
            {"patch_name": f"{arm}.wrong-semantics.patch", "intent": task.wrong_semantics_intent,
             "intended_group": "new_behavior", "unrelated_results": unrelated},
        ],
        "evidence": dict.fromkeys(values["evidence"], UNSET_EVIDENCE),
        "tool_instructions": (
            "Implement the task within src/; run bun test ./tests/visible and tsc --noEmit -p "
            "tsconfig.json; submit with submit_output."
        ),
    })
    values["provenance"].update({
        "extraction_rules": [
            "Reuse the pass-through arm's source slice and public tests without behavior changes.",
            "Keep hidden checks and patches outside repository/.",
        ],
        "local_adaptations": [
            "Start from the stage-pass-through arm; only the package identity changes.",
            "Only modular preserves the dispatch architecture at the upstream pin.",
            "Keep private feature checks and patches outside each repository tree.",
        ],
        "dependency_lock_digests": {
            "package-lock.json": digest_bytes(tree["package-lock.json"].encode()),
        },
        "start_tree_digest": workflow_tree_digest(tree),
        "start_file_count": len(tree),
        "start_total_bytes": sum(len(source.encode()) for source in tree.values()),
    })
    return ExtensionScenarioSidecar.model_validate(values)


def author(task: ShapeTask, root: Path = PILOT.parent) -> None:
    """Rewrite one task's generated assets; its task.md and feature checks stay as written."""
    source = root / SOURCE_SCENARIO
    target = root / task.scenario
    template_identity = f"oakridge-dbos-{SOURCE_SCENARIO}"
    for generated in ("repository", "patches", "qualification"):
        shutil.rmtree(target / generated, ignore_errors=True)
    shutil.rmtree(target / "hidden" / "regression", ignore_errors=True)
    shutil.copytree(source / "hidden" / "regression", target / "hidden" / "regression")
    (target / "patches").mkdir()
    for arm in SHAPE_ARMS:
        tree = read_tree(source / "repository" / arm)
        for name in ("package.json", "package-lock.json"):
            tree[name] = tree[name].replace(template_identity, task.subject_id)
        materialize(target / "repository" / arm, tree)
        patches = arm_patches(tree, task, arm)
        for name, patch in patches.items():
            (target / "patches" / name).write_text(patch, encoding="utf-8")
        template = ExtensionScenarioSidecar.model_validate_json(
            (source / "qualification" / "arms" / arm / "sidecar.json").read_bytes()
        )
        sidecar = _sidecar(template, task, arm, tree, patches)
        directory = target / "qualification" / "arms" / arm
        directory.mkdir(parents=True)
        (directory / "sidecar.json").write_bytes(
            canonical_json(sidecar.model_dump(mode="json")) + b"\n"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True, choices=sorted(TASKS))
    author(TASKS[parser.parse_args().scenario])


if __name__ == "__main__":
    main()
