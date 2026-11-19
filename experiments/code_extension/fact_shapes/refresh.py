"""Refresh each arm sidecar's generator-derived fields after regenerating arms.

Run from experiments/ with
``python -m code_extension.fact_shapes.refresh --scenario <scenario>`` after
``code_extension.fact_shapes.generate``. The start tree's identity, the patch
inventory, the writable scope, the protected visible tests and the task requirements
are rewritten from the generated fixture, task.md and alignment.md. Evidence digests
are left as they are: qualification then reruns and rewrites the evidence these trees
produce, so a refreshed sidecar is never accepted on its own.
"""

import argparse
import json
from pathlib import Path

from assay.canonical import canonical_json, digest_bytes
from assay.investigations.workflow_correctness import workflow_tree_digest
from code_extension.fact_shapes.alignment import parse_map, task_sentences
from code_extension.fact_shapes.cells import CELLS
from code_extension.fact_shapes.generate import scenario_name
from code_extension.fixture import PILOT, read_tree
from code_extension.fixtures import ExtensionScenarioSidecar, touched_paths

SCENARIOS = frozenset(scenario_name(cell) for cell in CELLS)
ALIGNMENT = Path(__file__).resolve().parents[1] / "studies/fact-shapes-2026-11/alignment.md"
WRITABLE_SCOPE = ("src/", "db/", "stage/", "evidence_kind/", "route_permission/")
EXTRACTION_RULES = (
    "Every arm declares the value list in its feature types.ts; only the arm's holder keeps "
    "an independent copy, and holders sit where a service keeps them.",
)
LOCAL_ADAPTATIONS = (
    "Independent holders: missing the arm's holder leaves every other behavior passing; "
    "omissions update the type and skip only one fact's file.",
)


def refresh(scenario: str, root: Path = PILOT.parent) -> list[str]:
    """Rewrite every arm sidecar of one scenario; return the arms whose sidecar changed."""
    if scenario not in SCENARIOS:
        raise ValueError(f"not a fact-shapes scenario: {scenario}")
    directory = root / scenario
    requirements = task_sentences((directory / "task.md").read_text())
    sentences = parse_map(ALIGNMENT.read_text())
    changed: list[str] = []
    for cell in CELLS:
        if scenario_name(cell) != scenario:
            continue
        tree = read_tree(directory / "repository" / cell.shape)
        path = directory / "qualification" / "arms" / cell.shape / "sidecar.json"
        data = json.loads(path.read_bytes())
        before = json.loads(path.read_bytes())
        data["provenance"].update({
            "start_tree_digest": workflow_tree_digest(tree),
            "start_file_count": len(tree),
            "start_total_bytes": sum(len(source.encode()) for source in tree.values()),
            "dependency_lock_digests": {
                "package-lock.json": digest_bytes(tree["package-lock.json"].encode()),
            },
            "extraction_rules": list(EXTRACTION_RULES),
            "local_adaptations": list(LOCAL_ADAPTATIONS),
        })
        data["writable_implementation_scope"] = list(WRITABLE_SCOPE)
        data["protected_assets"]["test_files"] = sorted(
            name for name in tree if name.startswith("tests/visible/")
        )
        data["public_requirements"] = list(requirements)
        links = []
        for fact, shape in (
            *((other.fact_id, other.shape) for other in CELLS if scenario_name(other) == scenario),
            (cell.anchor_fact_id, "anchor"),
        ):
            citation = sentences[scenario, f"fact:{fact}: {shape} behavior"]
            if citation not in requirements:
                raise ValueError(f"{fact}: alignment sentence is not in task.md")
            links.append({
                "assertion_id": str(fact), "citation": citation,
                "citation_kind": "public_requirement",
            })
        links.extend(
            link for link in data["requirements_to_tests"]
            if link["citation_kind"] == "preexisting_behavior"
        )
        data["requirements_to_tests"] = links
        names = (
            f"{cell.shape}.reference.patch",
            f"{cell.shape}.drop-{cell.fact_id}.patch",
            f"{cell.shape}.drop-{cell.anchor_fact_id}.patch",
        )
        inventory = []
        for name in names:
            patch = (directory / "patches" / name).read_text(encoding="utf-8")
            inventory.append({
                "arm_id": cell.shape,
                "digest": digest_bytes(patch.encode()),
                "intent": name,
                "kind": "reference" if name.endswith(".reference.patch") else "incomplete",
                "touched_paths": list(touched_paths(patch)),
            })
        data["patch_inventory"] = inventory
        ExtensionScenarioSidecar.model_validate(data)
        if data == before:
            continue
        path.write_bytes(canonical_json(data) + b"\n")
        changed.append(cell.shape)
    return changed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True, action="append", dest="scenarios")
    for name in parser.parse_args().scenarios:
        print(name, ", ".join(refresh(name)) or "unchanged")
