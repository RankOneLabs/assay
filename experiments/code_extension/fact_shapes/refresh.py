"""Refresh each arm sidecar's start-tree identity after regenerating arms.

Run from experiments/ with
``python -m code_extension.fact_shapes.refresh --scenario <scenario>`` after
``code_extension.fact_shapes.generate``. Only the start tree's digest, file count and
byte total change. Qualification then reruns and rewrites the evidence these trees
produce, so a refreshed sidecar is never accepted on its own.
"""

import argparse
import json
from pathlib import Path

from assay.canonical import canonical_json
from assay.investigations.workflow_correctness import workflow_tree_digest
from code_extension.fact_shapes.cells import CELLS
from code_extension.fact_shapes.generate import scenario_name
from code_extension.fixture import PILOT, read_tree
from code_extension.fixtures import ExtensionScenarioSidecar

SCENARIOS = frozenset(scenario_name(cell) for cell in CELLS)


def refresh(scenario: str, root: Path = PILOT.parent) -> list[str]:
    """Rewrite every arm sidecar of one scenario; return the arms whose identity changed."""
    if scenario not in SCENARIOS:
        raise ValueError(f"not a fact-shapes scenario: {scenario}")
    changed: list[str] = []
    for cell in CELLS:
        if scenario_name(cell) != scenario:
            continue
        tree = read_tree(root / scenario / "repository" / cell.shape)
        path = root / scenario / "qualification" / "arms" / cell.shape / "sidecar.json"
        data = json.loads(path.read_bytes())
        provenance = data["provenance"]
        identity = {
            "start_tree_digest": workflow_tree_digest(tree),
            "start_file_count": len(tree),
            "start_total_bytes": sum(len(source.encode()) for source in tree.values()),
        }
        if all(provenance[key] == value for key, value in identity.items()):
            continue
        provenance.update(identity)
        ExtensionScenarioSidecar.model_validate(data)
        path.write_bytes(canonical_json(data) + b"\n")
        changed.append(cell.shape)
    return changed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True, action="append", dest="scenarios")
    for name in parser.parse_args().scenarios:
        print(name, ", ".join(refresh(name)) or "unchanged")
