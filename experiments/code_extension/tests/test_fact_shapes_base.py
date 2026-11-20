"""Contract checks on precisely the tree given to study agents."""

from __future__ import annotations

import json
import re
from pathlib import Path

from code_extension.fact_shapes.cells import CELLS
from code_extension.fixture import read_tree

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "experiments/code_extension/fact_shapes/base"
LIBRARY = ROOT / "integrations/pier/scenario_library"


def test_package_and_lock_match_image() -> None:
    package = json.loads((BASE / "package.json").read_text())
    library = json.loads((LIBRARY / "package.json").read_text())
    for key in ("dependencies", "devDependencies", "overrides"):
        assert package[key] == library[key]
    lock = json.loads((BASE / "package-lock.json").read_text())
    original = json.loads((LIBRARY / "package-lock.json").read_text())
    lock["packages"][""]["name"] = original["packages"][""]["name"]
    assert lock["packages"] == original["packages"]
    assert package["private"] is True
    assert package["type"] == "module"
    assert package["scripts"] == {"test": "bun test", "typecheck": "tsc --noEmit -p tsconfig.json"}
    assert not list(BASE.rglob("node_modules"))


def test_only_locked_imports() -> None:
    lock = json.loads((LIBRARY / "package-lock.json").read_text())
    packages = {key.removeprefix("node_modules/") for key in lock["packages"] if key}
    for path in BASE.rglob("*.ts"):
        for specifier in re.findall(
            r"""(?:\bfrom\s+|^\s*import\s*)["']([^"']+)["']""",
            path.read_text(),
            flags=re.MULTILINE,
        ):
            if specifier.startswith(".") or specifier in {
                "bun:test", "bun:sqlite", "node:fs", "node:fs/promises",
            }:
                continue
            assert any(
                specifier == name or specifier.startswith(name + "/") for name in packages
            ), (path.relative_to(BASE), specifier)


def test_all_cells_have_files_and_planned_distances() -> None:
    assert len(CELLS) == 36
    for cell in CELLS:
        edit = BASE / cell.edit_site
        assert edit.is_file(), cell.fact_id
        for holder in cell.holders:
            target = BASE / holder
            assert target.is_file(), cell.fact_id
            left, right = edit.parent.parts, target.parent.parts
            common = 0
            for a, b in zip(left, right, strict=False):
                if a != b:
                    break
                common += 1
            assert len(left) + len(right) - 2 * common == cell.directory_hops
        if cell.shape != "reference":
            assert all(Path(holder).name not in edit.read_text() for holder in cell.holders)
    for feature in {cell.feature for cell in CELLS}:
        combinations = {(cell.shape, cell.task_type) for cell in CELLS if cell.feature == feature}
        assert len(combinations) == 12


def test_import_distances_match_cells() -> None:
    edges: dict[str, set[str]] = {}
    for path in BASE.rglob("*.ts"):
        edges[path.relative_to(BASE).as_posix()] = {
            (path.parent / specifier).resolve().relative_to(BASE.resolve()).as_posix()
            for specifier in re.findall(r"""from\s*["']([^"']+)["']""", path.read_text())
            if specifier.startswith(".")
        }
    for cell in CELLS:
        queue: list[tuple[str, int]] = [(cell.edit_site, 0)]
        visited: set[str] = set()
        distance = None
        while queue:
            node, hops = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            if node in cell.holders:
                distance = hops
                break
            queue.extend((target, hops + 1) for target in edges.get(node, set()))
        assert distance == cell.import_hops, cell.fact_id


def test_size_and_repository_loader() -> None:
    tree = read_tree(BASE)
    # Round 4: about 250 KB of application code, plus visible tests and the lockfile.
    assert 120 <= len(tree) <= 160
    assert 12000 <= sum(text.count("\n") for text in tree.values()) <= 16000
    source = sum(len(text.encode()) for path, text in tree.items()
                 if path.startswith("src/") and path.endswith(".ts"))
    assert 240_000 <= source <= 290_000
    assert not any(
        word in text
        for text in tree.values()
        for word in (
            "STAGE_ROUTING",
            "planner0",
            "EpicStatus",
            "EpicStage",
            "oakridge",
        )
    )


def test_feature_switch_points_are_specific_and_exhaustive() -> None:
    values = {
        "stage": ("queued", "triaged", "Stage"),
        "evidence_kind": ("document", "attestation", "EvidenceKind"),
        "route_permission": ("case_read", "case_inspect", "RoutePermission"),
    }
    for feature, (old, new, type_name) in values.items():
        edit = (BASE / feature / "edit.ts").read_text()
        types = (BASE / feature / "types.ts").read_text()
        assert types.startswith("export const values = [")
        assert f'"{old}"' in types
        assert f'"{new}"' not in types
        assert f"export type {type_name} = (typeof values)[number];" in types
        assert f"value: {type_name}" in edit
        assert f'vocabularyStore.record("{feature}",' in edit
        assert "return isValue(value);" in edit
        holders = [cell.holders[0] for cell in CELLS
                   if cell.feature == feature and cell.task_type == "additive"]
        for holder in holders:
            source = (BASE / holder).read_text()
            # In the base every holder derives from the type; no holder lists a value.
            assert f"'{old}'" not in source and f'"{old}"' not in source, holder
            assert f'"{new}"' not in source, holder
            if holder.endswith(".ts"):
                assert f"/{feature}/types.ts" in source or holder.startswith(f"{feature}/")
                assert "values" in source, holder
            if not holder.startswith(f"{feature}/"):
                # Shared holders name no feature in their file or directory names.
                for word in ("stage", "evidence", "kind", "permission"):
                    assert word not in holder, holder
            assert 'from "./edit.ts"' not in source
        sibling = next(BASE / cell.holders[0] for cell in CELLS
                       if cell.feature == feature and cell.shape == "sibling_only")
        assert "acceptsPeer" in sibling.read_text()
        assert sibling.name not in edit
