"""The scenario library: tasks cut from oakridge `1495ec34`, one module per task.

Each module in this package defines `TASKS`, a tuple of `LibraryTask`. A task names its
slice (the pinned files it ships and their relocation edits), its held patches as exact
edits against the start tree, and the public requirements its hidden assertions check.
Modules are discovered, so adding a task touches only its own module and fixture.

    uv run python -m code_extension.library patches --scenario worker-silence-bound
    uv run python -m code_extension.library sidecar --scenario worker-silence-bound
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass

from code_extension.slice import LIBRARY_PIN, SliceSpec

Edit = tuple[str, str, str]  # (path, exact old text, new text); old must occur exactly once
# patch file name -> (intent, edits); "reference.patch" is the known-good one
Patches = dict[str, tuple[str, tuple[Edit, ...]]]
# (public requirement, ids of the hidden assertions that check it)
Requirements = tuple[tuple[str, tuple[str, ...]], ...]

WRITABLE_SCOPE = ("src/", "tests/agent/")
REGRESSION = "Existing visible and hidden regression tests continue to pass."
TOOL_INSTRUCTIONS = (
    "Work within src/; keep shipped tests, dependencies and configuration unchanged. Run "
    "bun test ./tests/visible and tsc --noEmit -p tsconfig.json, then submit with submit_output."
)
RELOCATION = (
    "Only relative import paths change, as each file moves; the slice spec lists every edit."
)
HIDDEN_MOVE = "Pinned tests that point at the non-local edit move to the hidden regression group."


@dataclass(frozen=True)
class LibraryTask:
    scenario: str  # fixture directory name under code_extension/fixtures/
    slice: SliceSpec
    patches: Patches
    requirements: Requirements
    # An attempt whose patch names none of these outside tests/, in any spelling, omitted
    # the feature rather than failed to reach it (the study plan's "omitted" outcome).
    feature_tokens: tuple[str, ...] = ()
    # provenance: what changed from the pinned sources, beyond relocation
    local_adaptations: tuple[str, ...] = (RELOCATION, HIDDEN_MOVE)
    writable_scope: tuple[str, ...] = WRITABLE_SCOPE
    tool_instructions: str = TOOL_INSTRUCTIONS

    @property
    def subject_id(self) -> str:
        return self.slice.package_name


def _discover() -> dict[str, LibraryTask]:
    tasks: dict[str, LibraryTask] = {}
    for module in sorted(pkgutil.iter_modules(__path__), key=lambda item: item.name):
        if module.name.startswith("_"):
            continue
        for task in importlib.import_module(f"{__name__}.{module.name}").TASKS:
            if task.scenario in tasks:
                raise ValueError(f"scenario {task.scenario} is declared twice")
            tasks[task.scenario] = task
    return tasks


TASKS: dict[str, LibraryTask] = _discover()
SLICES = {name: task.slice for name, task in TASKS.items()}
PATCHES = {name: task.patches for name, task in TASKS.items()}
REQUIREMENTS = {name: task.requirements for name, task in TASKS.items()}
SUBJECTS = {name: task.subject_id for name, task in TASKS.items()}


def feature_tokens(subject_id: str) -> tuple[str, ...] | None:
    """The names a library subject's genuine attempt must add, or None for other subjects."""
    for task in TASKS.values():
        if task.subject_id == subject_id:
            if not task.feature_tokens:
                raise ValueError(f"{task.scenario} declares no feature token")
            return task.feature_tokens
    return None


def manifest_scope(subject_id: str) -> tuple[str, tuple[str, ...]] | None:
    """A library subject's pin and the pinned source paths it ships, or None."""
    for scenario, subject in SUBJECTS.items():
        if subject == subject_id:
            return LIBRARY_PIN, tuple(sorted(SLICES[scenario].files))
    return None


def write_sidecar(scenario: str) -> None:
    """The sidecar before qualification: every evidence ref unset until the gates fill it."""
    from assay.canonical import canonical_json, digest_bytes
    from assay.investigations.workflow_correctness import workflow_tree_digest
    from code_extension.authoring import UNSET_EVIDENCE
    from code_extension.fixture import PILOT, VISIBLE_PREFIX, read_tree
    from code_extension.fixtures import ExtensionScenarioSidecar, touched_paths

    task = TASKS[scenario]
    directory = PILOT.parent / scenario
    tree = read_tree(directory / "repository")
    patches = {
        name: (directory / "patches" / name).read_text(encoding="utf-8") for name in task.patches
    }
    intents = {name: intent for name, (intent, _) in task.patches.items()}
    assertions = [assertion for _, ids in task.requirements for assertion in ids]
    sidecar = ExtensionScenarioSidecar.model_validate({
        "subject_id": task.subject_id,
        "writable_implementation_scope": list(task.writable_scope),
        "protected_assets": {
            "test_files": sorted(name for name in tree if name.startswith(VISIBLE_PREFIX)),
            "dependency_files": ["package.json", "package-lock.json"],
            "configuration_files": ["tsconfig.json"],
        },
        "public_requirements": [text for text, _ in task.requirements],
        "preexisting_behaviors": [REGRESSION],
        "test_assertions": [
            *({"assertion_id": item, "group_name": "new_behavior", "visibility": "hidden"}
              for item in assertions),
            {"assertion_id": "visible-regression", "group_name": "visible_regression",
             "visibility": "visible"},
            {"assertion_id": "hidden-regression", "group_name": "hidden_regression",
             "visibility": "hidden"},
        ],
        "requirements_to_tests": [
            *({"assertion_id": item, "citation": text, "citation_kind": "public_requirement"}
              for text, ids in task.requirements for item in ids),
            {"assertion_id": "visible-regression", "citation": REGRESSION,
             "citation_kind": "preexisting_behavior"},
            {"assertion_id": "hidden-regression", "citation": REGRESSION,
             "citation_kind": "preexisting_behavior"},
        ],
        "patch_inventory": [
            {"arm_id": "baseline",
             "kind": "reference" if name == "reference.patch" else "incomplete",
             "digest": digest_bytes(patch.encode()), "intent": intents[name],
             "touched_paths": list(touched_paths(patch))}
            for name, patch in patches.items()
        ],
        "evidence": dict.fromkeys(
            ("leak_scan", "access_probe", "no_op", "scripted_submission", "double_reproduction"),
            UNSET_EVIDENCE,
        ),
        "tool_instructions": task.tool_instructions,
        "negative_expectations": [
            {"patch_name": name, "intent": intents[name], "intended_group": "new_behavior",
             "unrelated_results": {"hidden_regression": "passed", "visible_regression": "passed"}}
            for name in patches if name != "reference.patch"
        ],
        "provenance": {
            "extraction_invocation": (
                f"uv run python -m code_extension.slice --scenario {scenario} "
                "--oakridge <oakridge> "
                f"(git show {LIBRARY_PIN}:<path> for each file the scenario's module in "
                "code_extension/library/ lists)"
            ),
            "extraction_rules": [
                "Ship the pinned import closure of the files the feature passes through, and the "
                "pinned tests that exercise them.",
                "Keep hidden checks, patches and qualification assets outside repository/.",
            ],
            "licenses": [
                "Oakridge is private source at the pinned commit; no standalone license file "
                "is present.",
                "The locked third-party packages carry their notices in package-lock.json.",
            ],
            "local_adaptations": list(task.local_adaptations),
            "start_tree_digest": workflow_tree_digest(tree),
            "start_file_count": len(tree),
            "start_total_bytes": sum(len(source.encode()) for source in tree.values()),
            "dependency_lock_digests": {
                "package-lock.json": digest_bytes(tree["package-lock.json"].encode()),
            },
        },
    })
    target = directory / "qualification" / "sidecar.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(canonical_json(sidecar.model_dump(mode="json")) + b"\n")


def apply_edits(tree: dict[str, str], edits: tuple[Edit, ...]) -> dict[str, str]:
    after = dict(tree)
    for path, old, new in edits:
        if path not in after and old == "":
            after[path] = new  # an edit with empty old text creates a new file
            continue
        found = after.get(path, "").count(old)
        if found != 1:
            raise ValueError(f"{path}: expected one {old[:60]!r}, found {found}")
        after[path] = after[path].replace(old, new)
    return after


def render_patches(scenario: str) -> dict[str, str]:
    """Every held patch, rendered from its edits against the committed start tree."""
    from code_extension.authoring import unified_patch
    from code_extension.fixture import PILOT, read_tree

    tree = read_tree(PILOT.parent / scenario / "repository")
    return {
        name: unified_patch(tree, apply_edits(tree, edits))
        for name, (_, edits) in PATCHES[scenario].items()
    }


def write_patches(scenario: str) -> None:
    from code_extension.fixture import PILOT

    directory = PILOT.parent / scenario / "patches"
    directory.mkdir(exist_ok=True)
    for name, patch in render_patches(scenario).items():
        (directory / name).write_text(patch, encoding="utf-8")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="code_extension.library")
    parser.add_argument("step", choices=("patches", "sidecar"))
    parser.add_argument("--scenario", required=True, choices=sorted(PATCHES))
    args = parser.parse_args()
    (write_patches if args.step == "patches" else write_sidecar)(args.scenario)
