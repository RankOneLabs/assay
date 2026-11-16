"""Distance resolution and planned layout checks."""

from pathlib import Path

from code_extension.fact_shapes.cells import CELLS
from code_extension.fact_shapes.distance import directory_hops, import_hops, imports
from code_extension.fixture import read_tree


def test_import_distances() -> None:
    tree = {
        'src/a.ts': 'import { b } from "./b"; import "package";',
        'src/b.ts': 'export { c } from "./c.ts";',
        'src/c.ts': 'import "../folder";',
        'folder/index.ts': 'import "../src/a.ts";',
        'unreachable.ts': '',
    }
    assert imports(tree, 'src/a.ts') == ('src/b.ts',)
    assert import_hops(tree, 'src/a.ts', ['src/c.ts']) == 2
    assert import_hops(tree, 'src/a.ts', ['folder/index.ts']) == 3
    assert import_hops(tree, 'src/a.ts', ['unreachable.ts']) is None
    assert import_hops(tree, 'src/a.ts', ['src/a.ts']) == 0


def test_directory_distances() -> None:
    assert directory_hops('src/a/x.ts', ['src/b/y.ts']) == 2
    assert directory_hops('src/a/x.ts', ['src/a/y.ts']) == 0
    assert directory_hops('src/a/x.ts', ['src/b/y.ts', 'src/a/z.ts']) == 0


def test_base_planned_distances() -> None:
    root = Path(__file__).resolve().parents[1] / 'fact_shapes/base'
    tree = read_tree(root)
    for cell in CELLS:
        assert directory_hops(cell.edit_site, cell.holders) == cell.directory_hops
        assert import_hops(tree, cell.edit_site, cell.holders) == cell.import_hops


def test_resolution_forms() -> None:
    tree = {
        'src/a.ts': '''import type {
          Thing,
        } from "../types";
        export * from "../view";
        import "./setup.ts";
        import "missing-package";''',
        'types/index.ts': '',
        'view.tsx': '',
        'src/setup.ts': '',
    }
    assert imports(tree, 'src/a.ts') == ('types/index.ts', 'view.tsx', 'src/setup.ts')
